/* Fast cached path for Windows. Complex plans and cache misses run costguard.py. */
#include <ctype.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <process.h>
#include <windows.h>
#include "sqlite3.h"

#define SCALE 100000000LL
#define MAX_INPUT (64*1024*1024)
static sqlite3_stmt *getter;
static sqlite3 *db;
static int hits;
static char *plan_data;
static char *temp_plan;

typedef struct {
    char *address, *kind, *region, *sku, *action;
    int64_t old_cost, new_cost;
} Row;

static char *copy(const char *s) {
    if (!s) return NULL;
    size_t n=strlen(s)+1;
    char *p=(char*)malloc(n);
    if (p) memcpy(p,s,n);
    return p;
}

static char *field(const char *object,const char *path) {
    if (!object) return NULL;
    sqlite3_reset(getter);
    sqlite3_clear_bindings(getter);
    sqlite3_bind_text(getter,1,object,-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(getter,2,path,-1,SQLITE_TRANSIENT);
    if (sqlite3_step(getter)!=SQLITE_ROW) return NULL;
    return copy((const char*)sqlite3_column_text(getter,0));
}

static int64_t fixed(const char *s,int *ok) {
    if (!s || !*s) { *ok=0; return 0; }
    int negative=0;
    if (*s=='-') { negative=1; s++; }
    if (!isdigit((unsigned char)*s)) { *ok=0; return 0; }
    int64_t whole=0,frac=0,place=SCALE/10;
    while (isdigit((unsigned char)*s)) {
        if (whole>100000000) { *ok=0; return 0; }
        whole=whole*10+(*s++-'0');
    }
    if (*s=='.') {
        s++;
        if (!isdigit((unsigned char)*s)) { *ok=0; return 0; }
        while (isdigit((unsigned char)*s)) {
            if (!place) { *ok=0; return 0; }
            frac+=(*s++-'0')*place;
            place/=10;
        }
    }
    if (*s) { *ok=0; return 0; }
    return (whole*SCALE+frac)*(negative?-1:1);
}

static void amount(int64_t value,char *out,size_t size) {
    uint64_t n=(uint64_t)(value<0?-value:value);
    uint64_t cents=(n+SCALE/200)/(SCALE/100);
    snprintf(out,size,"%s%llu.%02llu",value<0?"-":"",(unsigned long long)(cents/100),
             (unsigned long long)(cents%100));
}

static int simple(const char *s) {
    if (!s || !*s) return 0;
    for (;*s;s++) if (!isalnum((unsigned char)*s) && *s!='_' && *s!='-') return 0;
    return 1;
}

static int same_ci(const char *a,const char *b) {
    if (!a || !b) return 0;
    while (*a && *b) {
        if (tolower((unsigned char)*a++)!=tolower((unsigned char)*b++)) return 0;
    }
    return *a==0 && *b==0;
}

static void normalize(char *s) {
    char *d=s;
    for (;*s;s++) if (!isspace((unsigned char)*s)) *d++=(char)tolower((unsigned char)*s);
    *d=0;
}

static int free_type(const char *s) {
    static const char *types[]={"azurerm_resource_group","azurerm_virtual_network","azurerm_subnet",
        "azurerm_network_security_group","azurerm_network_security_rule","azurerm_network_interface",
        "azurerm_subnet_network_security_group_association",NULL};
    for (int i=0;types[i];i++) if (!strcmp(s,types[i])) return 1;
    return 0;
}

static int disk_tier(int size,char *tier) {
    static const int sizes[]={4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384,32767};
    static const char *names[]={"P1","P2","P3","P4","P6","P10","P15","P20","P30","P40","P50","P60","P70","P80"};
    for (int i=0;i<14;i++) if (size<=sizes[i]) { strcpy(tier,names[i]); return 1; }
    return 0;
}

static int cached_price(const char *key,const char *region,const char *currency,int64_t *out) {
    sqlite3_stmt *stmt=NULL;
    const char *sql="SELECT json_extract(raw_json,'$.retailPrice'), json_extract(raw_json,'$.unitOfMeasure'), cached_at "
                    "FROM pricing_cache WHERE sku=?1 AND region=?2 AND currency=?3";
    if (sqlite3_prepare_v2(db,sql,-1,&stmt,NULL)!=SQLITE_OK) return 0;
    sqlite3_bind_text(stmt,1,key,-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt,2,region,-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt,3,currency,-1,SQLITE_TRANSIENT);
    int found=0;
    if (sqlite3_step(stmt)==SQLITE_ROW) {
        int ok=1;
        const char *price=(const char*)sqlite3_column_text(stmt,0);
        const char *unit=(const char*)sqlite3_column_text(stmt,1);
        sqlite3_int64 cached_at=sqlite3_column_int64(stmt,2);
        int64_t value=fixed(price,&ok);
        int expired=(sqlite3_int64)time(NULL)-cached_at>=86400;
        if (unit && ok && value>=0 && !expired) {
            if (!strcmp(unit,"1 Hour") && value<INT64_MAX/730) { *out=value*730; found=1; }
            else if (!strcmp(unit,"1/Month")) { *out=value; found=1; }
        }
    }
    sqlite3_finalize(stmt);
    if (found) hits++;
    return found;
}

static int state_price(const char *kind,const char *state,const char *currency,int64_t *out,char **region_out,char **sku_out) {
    char *location=field(state,"$.location");
    if (!location) return 0;
    normalize(location);
    if (!simple(location)) { free(location); return 0; }
    char key[1024],label[128];
    if (!strcmp(kind,"azurerm_linux_virtual_machine") || !strcmp(kind,"azurerm_windows_virtual_machine")) {
        char *sku=field(state,"$.size");
        if (!sku) sku=field(state,"$.vm_size");
        char *priority=field(state,"$.priority");
        char *os= !strcmp(kind,"azurerm_windows_virtual_machine") ? "windows":"linux";
        int spot=priority && same_ci(priority,"Spot");
        if (!sku || !simple(sku) || (priority && !same_ci(priority,"Spot") && !same_ci(priority,"Regular"))) {
            free(location);free(sku);free(priority);return 0;
        }
        snprintf(key,sizeof(key),"{\"os\": \"%s\", \"service\": \"Virtual Machines\", \"sku\": \"%s\", \"spot\": %s}",os,sku,spot?"true":"false");
        snprintf(label,sizeof(label),"%s",sku);
        free(sku);free(priority);
    } else if (!strcmp(kind,"azurerm_managed_disk")) {
        char *storage=field(state,"$.storage_account_type");
        char *size_text=field(state,"$.disk_size_gb");
        char *custom_tier=field(state,"$.tier");
        char *shares=field(state,"$.max_shares");
        char *burst=field(state,"$.on_demand_bursting_enabled");
        int size=size_text?atoi(size_text):0;
        char tier[8],redundancy[4];
        int good=storage && (!strcmp(storage,"Premium_LRS") || !strcmp(storage,"Premium_ZRS")) &&
            size>0 && disk_tier(size,tier) && (!custom_tier || !strcmp(custom_tier,tier)) &&
            (!shares || atoi(shares)<=1) && (!burst || strcmp(burst,"1"));
        if (!good) { free(location);free(storage);free(size_text);free(custom_tier);free(shares);free(burst);return 0; }
        strcpy(redundancy,!strcmp(storage,"Premium_LRS")?"LRS":"ZRS");
        snprintf(label,sizeof(label),"%s %s",tier,redundancy);
        snprintf(key,sizeof(key),"{\"meter\": \"%s Disk\", \"product\": \"Premium SSD Managed Disks\", \"service\": \"Storage\", \"sku\": \"%s\"}",label,label);
        free(storage);free(size_text);free(custom_tier);free(shares);free(burst);
    } else { free(location);return 0; }
    int ok=cached_price(key,location,currency,out);
    if (!ok) { free(location);return 0; }
    *region_out=location;
    *sku_out=copy(label);
    return *sku_out!=NULL;
}

static int unknown_after(const char *resource) {
    const char *attrs[]={"size","vm_size","location","disk_size_gb","storage_account_type","priority",NULL};
    for (int i=0;attrs[i];i++) {
        char path[96];
        snprintf(path,sizeof(path),"$.change.after_unknown.%s",attrs[i]);
        char *v=field(resource,path);
        int unknown=v && !strcmp(v,"1");
        free(v);
        if (unknown) return 1;
    }
    return 0;
}

static char *read_stream(FILE *in) {
    size_t cap=65536,n=0;
    char *buf=(char*)malloc(cap);
    if (!buf) return NULL;
    for (;;) {
        if (n+32768+1>cap) {
            cap*=2;
            if (cap>MAX_INPUT) { free(buf);return NULL; }
            char *newbuf=(char*)realloc(buf,cap);
            if (!newbuf) { free(buf);return NULL; }
            buf=newbuf;
        }
        size_t got=fread(buf+n,1,32768,in);
        n+=got;
        if (got<32768) break;
    }
    buf[n]=0;
    return buf;
}

/* Quote each argument using the Windows command-line parsing rules. */
static void append_arg(char **dest,const char *arg) {
    char *out=*dest;
    *out++='"';
    const char *p=arg;
    while (*p) {
        int slashes=0;
        while (*p=='\\') { slashes++;p++; }
        if (*p=='"') {
            for (int i=0;i<slashes*2+1;i++) *out++='\\';
            *out++='"';p++;
        } else if (!*p) {
            for (int i=0;i<slashes*2;i++) *out++='\\';
        } else {
            for (int i=0;i<slashes;i++) *out++='\\';
            *out++=*p++;
        }
    }
    *out++='"';*out++=' ';*out=0;
    *dest=out;
}

static int python_fallback(int argc,char **argv) {
    char exe[MAX_PATH],script[MAX_PATH],temp[MAX_PATH],dir[MAX_PATH];
    GetModuleFileNameA(NULL,exe,MAX_PATH);
    char *slash=strrchr(exe,'\\');
    if (!slash) return 2;
    *(slash+1)=0;
    snprintf(script,sizeof(script),"%scostguard.py",exe);
    int has_plan=0;
    for (int i=1;i<argc;i++) if (!strcmp(argv[i],"--plan")) has_plan=1;
    if (plan_data && !has_plan) {
        GetTempPathA(MAX_PATH,dir);
        if (!GetTempFileNameA(dir,"cg-",0,temp)) return 2;
        FILE *out=fopen(temp,"wb");
        if (!out) return 2;
        fwrite(plan_data,1,strlen(plan_data),out);
        fclose(out);
        temp_plan=copy(temp);
    }
    const char **args=(const char**)calloc((size_t)argc+8,sizeof(char*));
    if (!args) return 2;
    int n=0;
    args[n++]="py";args[n++]="-X";args[n++]="utf8";args[n++]=script;
    for (int i=1;i<argc;i++) args[n++]=argv[i];
    if (temp_plan) { args[n++]="--plan";args[n++]=temp_plan; }
    args[n]=NULL;
    size_t length=1;
    for (int i=0;i<n;i++) length+=strlen(args[i])*2+4;
    char *command=(char*)calloc(length,1);
    int code=2;
    if (command) {
        char *end=command;
        for (int i=0;i<n;i++) append_arg(&end,args[i]);
        STARTUPINFOA startup={0};
        PROCESS_INFORMATION process={0};
        startup.cb=sizeof(startup);
        if (CreateProcessA(NULL,command,NULL,NULL,TRUE,0,NULL,NULL,&startup,&process)) {
            WaitForSingleObject(process.hProcess,INFINITE);
            DWORD exit_code=2;
            if (GetExitCodeProcess(process.hProcess,&exit_code)) code=(int)exit_code;
            CloseHandle(process.hThread);CloseHandle(process.hProcess);
        }
        free(command);
    }
    free(args);
    if (temp_plan) { DeleteFileA(temp_plan);free(temp_plan); }
    return code;
}

int main(int argc,char **argv) {
    const char *plan_path=NULL,*cache_path="pricing_cache.db",*currency="USD",*threshold="50";
    int fallback=0,offline=0;
    for (int i=1;i<argc;i++) {
        if ((!strcmp(argv[i],"--plan") || !strcmp(argv[i],"--cache") ||
             !strcmp(argv[i],"--currency") || !strcmp(argv[i],"--max-increase")) && i+1<argc) {
            const char *flag=argv[i++];
            if (!strcmp(flag,"--plan")) plan_path=argv[i];
            else if (!strcmp(flag,"--cache")) cache_path=argv[i];
            else if (!strcmp(flag,"--currency")) currency=argv[i];
            else threshold=argv[i];
        } else if (!strcmp(argv[i],"--offline")) {
            offline=1;
        } else if (!strcmp(argv[i],"--strict")) {
        } else fallback=1;
    }
    if (fallback || !simple(currency)) return python_fallback(argc,argv);
    int ok=1;
    int64_t limit=fixed(threshold,&ok);
    if (!ok) return python_fallback(argc,argv);
    if (plan_path) {
        FILE *in=fopen(plan_path,"rb");
        if (!in) return python_fallback(argc,argv);
        plan_data=read_stream(in);fclose(in);
    } else if (!_isatty(0)) plan_data=read_stream(stdin);
    if (!plan_data || sqlite3_open_v2(cache_path,&db,SQLITE_OPEN_READONLY,NULL)!=SQLITE_OK)
        return python_fallback(argc,argv);
    if (sqlite3_prepare_v2(db,"SELECT json_extract(?1,?2)",-1,&getter,NULL)!=SQLITE_OK)
        return python_fallback(argc,argv);
    char *valid=field(plan_data,"$.resource_changes");
    if (!valid) return python_fallback(argc,argv);
    free(valid);
    sqlite3_stmt *q=NULL;
    if (sqlite3_prepare_v2(db,"SELECT value FROM json_each(?1,'$.resource_changes')",-1,&q,NULL)!=SQLITE_OK)
        return python_fallback(argc,argv);
    sqlite3_bind_text(q,1,plan_data,-1,SQLITE_TRANSIENT);
    Row *rows=NULL;
    int count=0,capacity=0,skipped=0;
    int64_t old_total=0,new_total=0;
    int bad=0;
    while (sqlite3_step(q)==SQLITE_ROW) {
        const char *raw=(const char*)sqlite3_column_text(q,0);
        char *resource=copy(raw),*kind=field(resource,"$.type"),*mode=field(resource,"$.mode");
        char *action=field(resource,"$.change.actions[0]");
        char *second=field(resource,"$.change.actions[1]");
        if (!kind || !action) { bad=1;free(resource);break; }
        if (free_type(kind) || (mode && !strcmp(mode,"data")) || !strcmp(action,"no-op") || !strcmp(action,"read")) {
            skipped++;free(resource);free(kind);free(mode);free(action);free(second);continue;
        }
        int create=!strcmp(action,"create") && !second;
        int remove=!strcmp(action,"delete") && !second;
        int update=!strcmp(action,"update") && !second;
        int replace=second && ((!strcmp(action,"delete")&&!strcmp(second,"create")) ||
                               (!strcmp(action,"create")&&!strcmp(second,"delete")));
        if ((!create&&!remove&&!update&&!replace) || unknown_after(resource)) { bad=1;free(resource);break; }
        Row row={0};
        row.address=field(resource,"$.address");row.kind=kind;
        row.action=copy(replace?"REPLACE":create?"CREATE":remove?"DELETE":"UPDATE");
        char *before=field(resource,"$.change.before"),*after=field(resource,"$.change.after");
        char *r1=NULL,*r2=NULL,*s1=NULL,*s2=NULL;
        if ((!create && !state_price(kind,before,currency,&row.old_cost,&r1,&s1)) ||
            (!remove && !state_price(kind,after,currency,&row.new_cost,&r2,&s2))) bad=1;
        if (!row.address || !simple(currency)) bad=1;
        row.region=copy(r2?r2:r1);row.sku=copy(s2?s2:s1);
        if (r1 && r2 && strcmp(r1,r2)) bad=1;
        if (s1 && s2 && strcmp(s1,s2)) {
            size_t len=strlen(s1)+strlen(s2)+5;
            free(row.sku);row.sku=(char*)malloc(len);
            if (row.sku) snprintf(row.sku,len,"%s -> %s",s1,s2);
        }
        if (!row.region || !row.sku || old_total>INT64_MAX-row.old_cost || new_total>INT64_MAX-row.new_cost) bad=1;
        free(r1);free(r2);free(s1);free(s2);free(before);free(after);free(resource);free(mode);free(action);free(second);
        if (bad) break;
        if (count==capacity) {
            capacity=capacity?capacity*2:16;
            Row *newrows=(Row*)realloc(rows,(size_t)capacity*sizeof(Row));
            if (!newrows) { bad=1;break; }
            rows=newrows;
        }
        rows[count++]=row;old_total+=row.old_cost;new_total+=row.new_cost;
    }
    if (sqlite3_errcode(db)!=SQLITE_OK && sqlite3_errcode(db)!=SQLITE_ROW && sqlite3_errcode(db)!=SQLITE_DONE) bad=1;
    sqlite3_finalize(q);
    if (bad) return python_fallback(argc,argv);
    int64_t delta=new_total-old_total;
    char old[64],now[64],diff[64],budget[64];
    amount(old_total,old,sizeof(old));amount(new_total,now,sizeof(now));amount(delta,diff,sizeof(diff));amount(limit,budget,sizeof(budget));
    printf("COSTGUARD: Azure Infrastructure Cost Impact Report\n");
    printf("Changed supported resources only | %s/month | VM baseline: 730 hours\n",currency);
    printf("%-39s  %-7s  %-12s  %-35s %10s %10s %10s\n","Resource Address","Action","Region","SKU / Meter","Old","New","Delta");
    for (int i=0;i<count;i++) {
        char a[64],b[64],c[64];
        amount(rows[i].old_cost,a,sizeof(a));amount(rows[i].new_cost,b,sizeof(b));amount(rows[i].new_cost-rows[i].old_cost,c,sizeof(c));
        char signed_delta[68];
        snprintf(signed_delta,sizeof(signed_delta),"%s%s",rows[i].new_cost>rows[i].old_cost?"+":"",c);
        printf("%-39s  %-7s  %-12s  %-35s %10s %10s %10s\n",rows[i].address,rows[i].action,
               rows[i].region,rows[i].sku,a,b,signed_delta);
    }
    printf("Prior: %s | Proposed: %s | Net impact: %s/mo\n",old,now,diff);
    printf("Cache: %d hits, 0 API requests | Skipped free/unchanged: %d\n",hits,skipped);
    printf("Budget threshold: %s | Status: %s | Exit: %d\n",budget,delta>limit?"FAILED":"PASSED",delta>limit?1:0);
    return delta>limit?1:0;
}

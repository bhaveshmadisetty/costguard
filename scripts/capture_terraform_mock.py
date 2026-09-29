"""Capture actual Terraform-planned Azure changes using a mocked AzureRM provider."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXAMPLE=ROOT/'examples'/'azure-mock'
TERRAFORM=ROOT/'tools'/'bin'/'terraform.exe'
result=subprocess.run([str(TERRAFORM),'test','-json','-verbose'],cwd=EXAMPLE,
                      text=True,capture_output=True,encoding='utf-8',errors='replace')
events=[]
for line in result.stdout.splitlines():
    try: events.append(json.loads(line))
    except json.JSONDecodeError: pass
summary=next((event.get('test_summary') for event in reversed(events) if event.get('type')=='test_summary'),None)
if result.returncode or not summary or summary.get('status')!='pass':
    errors=[event.get('@message','') for event in events if event.get('@level')=='error']
    raise SystemExit('Terraform mock test failed:\n'+'\n'.join(errors or [result.stderr[-2000:]]))
names={'create_plan':'terraform-azure-create','upgrade_plan':'terraform-azure-upgrade',
       'delete_plan':'terraform-azure-delete'}
found=set()
for event in events:
    if event.get('type')!='test_plan' or event.get('@testrun') not in names: continue
    label=event['@testrun']
    plan=event['test_plan']
    changes=plan.get('resource_changes',[])
    for resource in changes:
        for state in ('before','after'):
            values=resource.get('change',{}).get(state)
            if isinstance(values,dict) and 'admin_password' in values:
                values['admin_password']='<REDACTED>'
    output={'format_version':plan.get('plan_format_version','1.2'),
            'terraform_version':'1.16.4',
            'origin':'Terraform test -json -verbose; official AzureRM provider mocked; non-pricing password redacted',
            'resource_changes':changes}
    destination=ROOT/'test-plans'/(names[label]+'.json')
    destination.write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    found.add(label)
    print(names[label],[(r['type'],r['change']['actions']) for r in changes])
if found!=set(names):
    raise SystemExit('Missing Terraform plan events: '+str(set(names)-found))
print('Captured',len(found),'Terraform-generated Azure plans without an Azure subscription.')

"""CostGuard: auditable Azure Terraform cost deltas, using only Python's standard library."""
import argparse
import json
import sqlite3
import sys
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

API = 'https://prices.azure.com/api/retail/prices'
FREE = {'azurerm_resource_group', 'azurerm_virtual_network', 'azurerm_subnet',
        'azurerm_network_security_group', 'azurerm_network_security_rule',
        'azurerm_network_interface', 'azurerm_subnet_network_security_group_association'}
VM = {'azurerm_linux_virtual_machine', 'azurerm_windows_virtual_machine', 'azurerm_virtual_machine'}


class Unpriced(Exception):
    pass


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Numbers must be finite')
    return result


def money(value):
    return str(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def spec(kind, state):
    if not isinstance(state, dict):
        raise Unpriced('Missing resource state')
    region = state.get('location')
    if not isinstance(region, str) or not region.strip():
        raise Unpriced('Region is missing or unknown until apply')
    region = ''.join(region.lower().split())
    if kind in VM:
        sku = state.get('size') or state.get('vm_size')
        if not isinstance(sku, str) or not sku:
            raise Unpriced('VM size is missing or unknown until apply')
        if kind == 'azurerm_virtual_machine':
            windows = bool(state.get('os_profile_windows_config'))
            linux = bool(state.get('os_profile_linux_config'))
            if windows == linux:
                raise Unpriced('Legacy VM OS cannot be determined')
        else:
            windows = kind == 'azurerm_windows_virtual_machine'
        priority = str(state.get('priority') or 'Regular').lower()
        if priority not in ('regular', 'spot'):
            raise Unpriced('Unsupported VM priority')
        return dict(service='Virtual Machines', sku=sku, region=region,
                    os='windows' if windows else 'linux', spot=priority == 'spot')
    if kind == 'azurerm_managed_disk':
        storage = state.get('storage_account_type')
        if storage not in ('Premium_LRS', 'Premium_ZRS'):
            raise Unpriced('Only Premium LRS/ZRS managed disks are supported')
        size = state.get('disk_size_gb')
        tiers = [(4,'P1'),(8,'P2'),(16,'P3'),(32,'P4'),(64,'P6'),(128,'P10'),
                 (256,'P15'),(512,'P20'),(1024,'P30'),(2048,'P40'),(4096,'P50'),
                 (8192,'P60'),(16384,'P70'),(32767,'P80')]
        if not isinstance(size, (int, float)) or isinstance(size, bool) or size <= 0:
            raise Unpriced('Disk size is missing or invalid')
        tier = next((name for capacity,name in tiers if size <= capacity), None)
        if not tier:
            raise Unpriced('Disk size exceeds supported tiers')
        if state.get('tier') and state['tier'] != tier:
            raise Unpriced('Custom disk performance tiers are unsupported')
        if (state.get('max_shares') or 1) > 1 or state.get('on_demand_bursting_enabled'):
            raise Unpriced('Shared/bursting disk pricing is unsupported')
        return dict(service='Storage', sku=f'{tier} {storage.split("_")[1]}', region=region,
                    product='Premium SSD Managed Disks', meter=f'{tier} {storage.split("_")[1]} Disk')
    raise Unpriced('Unsupported potentially billable resource type')


def fetch(url, timeout):
    from urllib.request import urlopen, Request
    with urlopen(Request(url, headers={'User-Agent':'CostGuard/1.0'}), timeout=timeout) as response:
        return json.load(response, parse_float=str)


class Pricing:
    def __init__(self, path, currency='USD', timeout=10, offline=False, transport=fetch, retries=2, refresh=False):
        self.db = sqlite3.connect(path)
        self.db.execute('''CREATE TABLE IF NOT EXISTS pricing_cache (
            sku TEXT NOT NULL, region TEXT NOT NULL, currency TEXT NOT NULL,
            hourly_rate REAL NOT NULL, cached_at INTEGER NOT NULL,
            raw_json TEXT NOT NULL, source_url TEXT NOT NULL,
            PRIMARY KEY (sku,region,currency))''')
        self.currency, self.timeout, self.offline, self.transport, self.retries = currency, timeout, offline, transport, retries
        self.refresh = refresh
        self.hits = self.calls = 0
        self.failed = {}

    def clear(self):
        self.db.execute('DELETE FROM pricing_cache')
        self.db.commit()

    def rate(self, item):
        key = json.dumps({k:v for k,v in item.items() if k != 'region'}, sort_keys=True)
        cached = self.db.execute('SELECT raw_json,source_url,cached_at FROM pricing_cache WHERE sku=? AND region=? AND currency=?',
                                 (key,item['region'],self.currency)).fetchone()
        if cached and not self.refresh:
            self.hits += 1
            return self.result(json.loads(cached[0]), cached[1], cached[2], 'cache')
        failure_key = (key,item['region'],self.currency)
        if failure_key in self.failed:
            raise Unpriced(self.failed[failure_key])
        try:
            if self.offline:
                raise Unpriced('Offline: no cached price')
            from urllib.parse import urlencode, urlparse
            def quote(s):
                return "'" + s.replace("'", "''") + "'"
            filters = [f'serviceName eq {quote(item["service"])}',
                       f'armRegionName eq {quote(item["region"])}', "priceType eq 'Consumption'"]
            if item['service'] == 'Virtual Machines':
                filters.append(f'armSkuName eq {quote(item["sku"])}')
            else:
                filters.extend([f'productName eq {quote(item["product"])}', f'meterName eq {quote(item["meter"])}'])
            source = API + '?' + urlencode({'$filter':' and '.join(filters), 'currencyCode':quote(self.currency)})
            url, candidates, seen = source, [], set()
            while url:
                parsed = urlparse(url)
                if parsed.scheme != 'https' or parsed.hostname != 'prices.azure.com' or url in seen or len(seen) >= 100:
                    raise Unpriced('Invalid or excessive API pagination')
                seen.add(url)
                payload = self.request(url)
                for entry in payload['Items']:
                    if self.matches(entry, item):
                        candidates.append(entry)
                url = payload.get('NextPageLink')
            if not candidates:
                raise Unpriced(f"SKU '{item['sku']}' not found in Azure Retail API")
            # Multiple meter identities are ambiguous; never silently take the first result.
            identities = {e['meterId'] for e in candidates}
            if len(identities) != 1:
                raise Unpriced(f"Ambiguous pricing for {item['sku']}: {len(identities)} meters")
            entry = max(candidates, key=lambda e:e.get('effectiveStartDate',''))
            stamp = int(time.time())
            result = self.result(entry, source, stamp, 'api')
            self.db.execute('INSERT OR REPLACE INTO pricing_cache VALUES (?,?,?,?,?,?,?)',
                            (key,item['region'],self.currency,float(result['monthly']/730),stamp,json.dumps(entry),source))
            self.db.commit()
            return result
        except (OSError, ValueError, KeyError, TypeError, InvalidOperation, Unpriced) as error:
            message = ('Network unavailable: ' if isinstance(error, OSError) else '') + str(error)
            self.failed[failure_key] = message
            raise Unpriced(message) from error

    def request(self, url):
        from urllib.error import HTTPError
        from http.client import HTTPException
        for attempt in range(self.retries + 1):
            try:
                self.calls += 1
                return self.transport(url, self.timeout)
            except HTTPError as error:
                if error.code not in (408, 429, 500, 502, 503, 504) or attempt == self.retries:
                    raise
            except (OSError, TimeoutError, HTTPException):
                if attempt == self.retries:
                    raise
            time.sleep(min(0.5 * (2 ** attempt), 2))

    def matches(self, entry, item):
        if entry.get('type') != 'Consumption' or entry.get('currencyCode') != self.currency or entry.get('armRegionName') != item['region']:
            return False
        if entry.get('serviceName') != item['service']:
            return False
        if decimal(entry.get('tierMinimumUnits',0)) != 0:
            return False
        if entry.get('effectiveStartDate','') > time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()):
            return False
        if item['service'] == 'Virtual Machines':
            label = (entry.get('meterName','') + ' ' + entry.get('skuName','')).lower()
            return (entry.get('armSkuName') == item['sku'] and entry.get('unitOfMeasure') == '1 Hour'
                    and ('windows' in entry.get('productName','').lower()) == (item['os'] == 'windows')
                    and 'low priority' not in label and ('spot' in label) == item['spot'])
        return (entry.get('productName') == item['product'] and entry.get('meterName') == item['meter']
                and entry.get('unitOfMeasure') == '1/Month')

    def result(self, entry, url, stamp, source):
        unit = entry['unitOfMeasure']
        if unit not in ('1 Hour','1/Month'):
            raise Unpriced('Unsupported pricing unit: ' + unit)
        price = decimal(entry['retailPrice'])
        if price < 0:
            raise Unpriced('Negative retail price')
        return dict(monthly=price * (730 if unit == '1 Hour' else 1), meter=entry,
                    source_url=url, cached_at=stamp, source=source)


def analyze(plan, pricing, group_by=None):
    if isinstance(plan, dict) and 'resource_changes' not in plan and isinstance(plan.get('planned_values'),dict) and 'format_version' in plan:
        plan = dict(plan,resource_changes=[])
    if not isinstance(plan, dict) or not isinstance(plan.get('resource_changes'), list):
        raise ValueError('Expected a Terraform plan object with resource_changes[]')
    rows, warnings, skipped = [], [], 0
    for resource in plan['resource_changes']:
        if not isinstance(resource, dict) or not isinstance(resource.get('change'), dict):
            raise ValueError('Each resource must contain a change object')
        address, kind, change = resource.get('address'), resource.get('type'), resource['change']
        if not isinstance(address, str) or not isinstance(kind, str):
            raise ValueError('Each resource requires a string address and type')
        actions = change.get('actions')
        if actions in (['no-op'], ['read']) or kind in FREE or resource.get('mode') == 'data':
            skipped += 1
            continue
        if actions not in (['create'], ['delete'], ['update'], ['delete','create'], ['create','delete']):
            raise ValueError(f'{address}: unsupported action array {actions!r}')
        costs, proofs, labels, regions = [], [], [], []
        problem = None
        for side in ('before','after'):
            absent = (side == 'before' and actions == ['create']) or (side == 'after' and actions == ['delete'])
            if absent:
                costs.append(Decimal(0)); proofs.append(None)
                continue
            try:
                unknown = change.get('after_unknown') if side == 'after' else None
                price_keys = ('size','vm_size','location','priority') if kind in VM else ('location','disk_size_gb','storage_account_type')
                if unknown is True or (isinstance(unknown, dict) and any(unknown.get(k) for k in price_keys)):
                    raise Unpriced('Price-relevant values are unknown until apply')
                item = spec(kind, change.get(side))
                labels.append(item['sku']); regions.append(item['region'])
                proof = pricing.rate(item)
                costs.append(proof['monthly']); proofs.append(proof)
            except Unpriced as error:
                problem = str(error)
                costs.append(None); proofs.append(None)
        if problem:
            if problem.startswith(('Offline: no cached price', 'Network unavailable:')):
                warnings.append(f'{address}: Network unavailable; defaulting SKU to $0.00. Estimate incomplete.')
                # Do not turn a partially priced update into a false saving.
                costs = [Decimal(0), Decimal(0)]
            else:
                warnings.append(f'{address}: {problem}. Skipping cost; estimate incomplete.')
                costs = [None, None]
        state = change.get('after') or change.get('before') or {}
        tags = state.get('tags') or {} if isinstance(state,dict) else {}
        if not isinstance(tags,dict):
            tags = {}
        rows.append(dict(address=address, action='REPLACE' if len(actions)==2 else actions[0].upper(),
                         region=' -> '.join(dict.fromkeys(regions)), sku=' -> '.join(dict.fromkeys(labels)) or '?',
                         old=costs[0], new=costs[1], delta=None if None in costs else costs[1]-costs[0],
                         group=str(tags.get(group_by,'(untagged)')) if group_by else '', proofs=proofs))
    return rows, warnings, skipped


def summarize(rows, warnings, skipped, pricing, limit, strict=False):
    old = sum((r['old'] for r in rows if r['old'] is not None), Decimal(0))
    new = sum((r['new'] for r in rows if r['new'] is not None), Decimal(0))
    delta = new-old
    code = 1 if delta > limit else (2 if warnings and strict else 0)
    verdict = 'FAILED' if delta > limit else ('INCOMPLETE' if warnings else 'PASSED')
    result = dict(currency=pricing.currency, prior=old, proposed=new, delta=delta, threshold=limit,
                  status=verdict, exit_code=code, complete=not warnings, skipped=skipped,
                  cache_hits=pricing.hits, api_calls=pricing.calls, warnings=warnings, resources=rows)
    return result


def render(rows, warnings, skipped, pricing, limit, markdown=False, group_by=None, json_mode=False, strict=False):
    result = summarize(rows,warnings,skipped,pricing,limit,strict)
    old, new, delta, code, verdict = (result[k] for k in ('prior','proposed','delta','exit_code','status'))
    if json_mode:
        print(json.dumps(result, default=str, indent=2))
        return code
    print('COSTGUARD: Azure Infrastructure Cost Impact Report')
    print(f'Changed supported resources only | {pricing.currency}/month | VM baseline: 730 hours')
    headers = ['Resource Address','Action','Region','SKU / Meter','Old','New','Delta']
    table = []
    for row in rows:
        table.append([row['address'],row['action'],row['region'],row['sku']] +
                     [('UNKNOWN' if row[k] is None else ('+' if k=='delta' and row[k]>0 else '')+money(row[k])) for k in ('old','new','delta')])
    if markdown:
        def escape(value):
            return str(value).replace('|','\\|').replace('\n',' ')
        print('| ' + ' | '.join(headers) + ' |')
        print('| ' + ' | '.join(['---']*len(headers)) + ' |')
        for row in table:
            print('| ' + ' | '.join(map(escape,row)) + ' |')
    else:
        widths = [max(len(str(row[i])) for row in [headers]+table) for i in range(len(headers))]
        print('  '.join(s.ljust(w) for s,w in zip(headers,widths)))
        print('-' * (sum(widths)+12))
        for row in table:
            print('  '.join(str(s).ljust(w) for s,w in zip(row,widths)))
    if group_by:
        for group in sorted({r['group'] for r in rows}):
            total = sum((r['delta'] for r in rows if r['group']==group and r['delta'] is not None),Decimal(0))
            print(f'{group_by}={group}: {money(total)}/mo (known delta)')
    print(f'Prior: {money(old)} | Proposed: {money(new)} | Net impact: {money(delta)}/mo')
    print(f'Cache: {pricing.hits} hits, {pricing.calls} API requests | Skipped free/unchanged: {skipped}')
    print(f'Budget threshold: {money(limit)} | Status: {verdict} | Exit: {code}')
    for warning in warnings:
        print('[WARN] ' + warning, file=sys.stderr)
    if warnings:
        print('Totals include known costs only. Unpriced resources are not free; no complete budget assurance.')
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--max-increase', default='50')
    parser.add_argument('--currency', type=str.upper, choices=['USD','EUR','GBP','INR'], default='USD')
    parser.add_argument('--cache', type=Path, default=Path('pricing_cache.db'))
    parser.add_argument('--clear-cache', action='store_true')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='Fetch current Azure prices instead of using saved prices')
    parser.add_argument('--strict', action='store_true', help='Exit 2 on incomplete pricing')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--retries', type=int, default=2, help='Retries for transient API failures; default 2')
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--markdown', action='store_true')
    output.add_argument('--json', action='store_true')
    parser.add_argument('--group-by', metavar='TAG')
    args = parser.parse_args(argv)
    pricing = None
    try:
        limit = decimal(args.max_increase)
        if not 0 < args.timeout <= 120:
            raise ValueError('--timeout must be between 0 and 120 seconds')
        if not 0 <= args.retries <= 5:
            raise ValueError('--retries must be between 0 and 5')
        if args.offline and args.refresh:
            raise ValueError('--refresh cannot be combined with --offline')
        pricing = Pricing(args.cache, args.currency, args.timeout, args.offline, retries=args.retries, refresh=args.refresh)
        if args.clear_cache:
            pricing.clear()
            if args.plan is None and sys.stdin.isatty():
                print('Cache cleared.'); return 0
        if args.plan:
            plan = json.loads(args.plan.read_text(encoding='utf-8-sig'))
        elif not sys.stdin.isatty():
            raw = sys.stdin.read().lstrip('\ufeff')
            if args.clear_cache and not raw.strip():
                print('Cache cleared.'); return 0
            plan = json.loads(raw)
        else:
            parser.error('Supply --plan FILE or pipe Terraform plan JSON to stdin')
        rows, warnings, skipped = analyze(plan, pricing, args.group_by)
        return render(rows,warnings,skipped,pricing,limit,args.markdown,args.group_by,args.json,args.strict)
    except (OSError, ValueError, TypeError, InvalidOperation, sqlite3.Error) as error:
        print(f'[ERROR] {error}', file=sys.stderr)
        return 2
    finally:
        if pricing:
            pricing.db.close()


if __name__ == '__main__':
    sys.exit(main())

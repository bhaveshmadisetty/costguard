"""Generate synthetic Terraform-format fixtures. These are not terraform-produced plans."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'test-plans'
OUT.mkdir(exist_ok=True)


def vm(size='Standard_B1s', **kwargs):
    return dict(size=size, location='eastus', tags={'Team':'platform','Environment':'dev'}, **kwargs)


def change(name, actions, before=None, after=None, kind='azurerm_linux_virtual_machine'):
    return dict(address=f'{kind}.{name}', mode='managed', type=kind, name=name,
                provider_name='registry.terraform.io/hashicorp/azurerm',
                change=dict(actions=actions, before=before, after=after, after_unknown={}))


plans = {
    '01-create': [change('app',['create'],after=vm())],
    '02-delete': [change('old',['delete'],before=vm())],
    '03-upgrade': [change('app',['update'],vm('Standard_B2s'),vm('Standard_D2s_v3'))],
    '04-hostile-noise': [change(f'noise{i}',['create'],after={'name':f'noise{i}','location':'eastus'},
                               kind=['azurerm_resource_group','azurerm_virtual_network','azurerm_network_security_group','azurerm_subnet'][i%4]) for i in range(15)],
    '05-tags-only': [change('app',['update'],vm(),dict(vm(),tags={'Team':'other'}))],
    '06-replace': [change('app',['delete','create'],vm(),vm('Standard_B2s'))],
    '07-downgrade': [change('app',['update'],vm('Standard_B2s'),vm())],
    '08-unknown-sku': [change('unknown',['create'],after=vm('Custom_Unknown_SKU'))],
    '09-empty': [],
    'plan-a-small-add': [change('app',['create'],after=vm()),
                         change('data',['create'],after={'location':'eastus','storage_account_type':'Premium_LRS','disk_size_gb':128},kind='azurerm_managed_disk')],
    'plan-b-upgrade-delete': [change('app',['update'],vm('Standard_B2s'),vm('Standard_D2s_v3')),
                              change('old',['delete'],before=vm())],
}
unknown = change('pending',['create'],after=dict(vm(),size=None))
unknown['change']['after_unknown']={'size':True}
plans['10-unknown-value']=[unknown]
for name, resources in plans.items():
    (OUT / (name+'.json')).write_text(json.dumps({'format_version':'1.2','terraform_version':'1.9.0','resource_changes':resources},indent=2)+'\n',encoding='utf-8')
(OUT/'invalid.json').write_text('{ not valid JSON\n',encoding='utf-8')
print(f'Wrote {len(plans)} synthetic plans plus malformed input to {OUT}')

import contextlib
import io
import json
import uuid
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import costguard as c


def meter(sku='Standard_B1s', price='0.01', **extra):
    return dict(dict(type='Consumption',currencyCode='USD',armRegionName='eastus',
                     serviceName='Virtual Machines',unitOfMeasure='1 Hour',armSkuName=sku,
                     meterName=sku,skuName=sku,productName='Virtual Machines BS Series',
                     meterId=sku,retailPrice=price,isPrimaryMeterRegion=True),**extra)


def resource(actions, old=None, new=None, **extra):
    return dict(address='azurerm_linux_virtual_machine.app',type='azurerm_linux_virtual_machine',
                change=dict(actions=actions,before=old,after=new,**extra))


def vm(size='Standard_B1s'):
    return dict(size=size,location='East US')


class CostGuardTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'tmp'/'tests'
        root.mkdir(parents=True,exist_ok=True)
        self.folder=root/uuid.uuid4().hex
        self.folder.mkdir()
        self.path=self.folder/'cache.db'
        self.prices=[]
    def tearDown(self):
        for p in self.prices:
            p.db.close()
        assert self.folder.resolve().is_relative_to(Path(__file__).resolve().parents[1]/'tmp'/'tests')
        for file in self.folder.iterdir():
            file.unlink()
        self.folder.rmdir()
    def pricing(self, entries=None, transport=None, **kw):
        def fake(url,timeout):
            return {'Items':entries or [meter()], 'NextPageLink':None}
        p=c.Pricing(self.path,transport=transport or fake,**kw)
        self.prices.append(p)
        return p
    def analyze(self,p,*resources):
        return c.analyze({'resource_changes':list(resources)},p)
    def test_lifecycle_and_tag_zero(self):
        p=self.pricing()
        for actions,old,new,expected in [(['create'],None,vm(),'7.30'),(['delete'],vm(),None,'-7.30'),
                                        (['update'],vm(),dict(vm(),tags={'a':'b'}),'0'),
                                        (['delete','create'],vm(),vm(),'0'),(['create','delete'],vm(),vm(),'0')]:
            rows,warnings,_=self.analyze(p,resource(actions,old,new))
            self.assertEqual(rows[0]['delta'],Decimal(expected)); self.assertFalse(warnings)
    def test_upgrade_and_downsize(self):
        def transport(url,timeout):
            from urllib.parse import unquote
            sku='Standard_B2s' if 'Standard_B2s' in unquote(url) else 'Standard_B1s'
            return {'Items':[meter(sku,'0.04' if sku=='Standard_B2s' else '0.01')]}
        p=self.pricing(transport=transport)
        for a,b,delta in [('Standard_B1s','Standard_B2s','21.90'),('Standard_B2s','Standard_B1s','-21.90')]:
            rows,_,_=self.analyze(p,resource(['update'],vm(a),vm(b)))
            self.assertEqual(rows[0]['delta'],Decimal(delta))
    def test_filters_wrong_meters(self):
        p=self.pricing([meter(meterId='spot',meterName='B1s Spot'),meter(meterId='low',meterName='B1s Low Priority'),
                        meter(meterId='win',productName='Virtual Machines Windows'),meter(type='Reservation'),
                        meter(type='DevTestConsumption'),meter(currencyCode='EUR'),meter(armRegionName='westus'),meter()])
        result=p.rate(c.spec('azurerm_linux_virtual_machine',vm()))
        self.assertEqual(result['meter']['meterId'],'Standard_B1s')
    def test_regional_standard_meter_need_not_be_primary(self):
        p=self.pricing([meter(isPrimaryMeterRegion=False)])
        self.assertEqual(p.rate(c.spec('azurerm_linux_virtual_machine',vm()))['monthly'],Decimal('7.30'))
    def test_cache_persists_without_network(self):
        item=c.spec('azurerm_linux_virtual_machine',vm())
        p=self.pricing(); first=p.rate(item)
        q=self.pricing(transport=lambda *_:self.fail('Network used on cache hit'))
        self.assertEqual(q.rate(item)['monthly'],first['monthly'])
        self.assertEqual((q.hits,q.calls),(1,0))
        q.clear()
        self.assertEqual(q.db.execute('SELECT count(*) FROM pricing_cache').fetchone()[0],0)
    def test_currency_isolation(self):
        item=c.spec('azurerm_linux_virtual_machine',vm())
        self.pricing().rate(item)
        p=self.pricing([meter(currencyCode='EUR',price='0.02')],currency='EUR')
        self.assertEqual(p.rate(item)['monthly'],Decimal('14.60'))
        self.assertEqual(p.calls,1)
    def test_windows_and_spot_cache_isolation(self):
        self.pricing().rate(c.spec('azurerm_linux_virtual_machine',vm()))
        p=self.pricing([meter(productName='Virtual Machines Windows',price='0.02')])
        self.assertEqual(p.rate(c.spec('azurerm_windows_virtual_machine',vm()))['monthly'],Decimal('14.60'))
        self.assertEqual(p.calls,1)
        q=self.pricing([meter(meterName='B1s Spot',price='0.003')])
        self.assertEqual(q.rate(c.spec('azurerm_linux_virtual_machine',dict(vm(),priority='Spot')))['monthly'],Decimal('2.190'))
    def test_disk_monthly_unit_and_product(self):
        item=c.spec('azurerm_managed_disk',dict(location='eastus',storage_account_type='Premium_LRS',disk_size_gb=128))
        good=meter(serviceName='Storage',productName='Premium SSD Managed Disks',meterName='P10 LRS Disk',unitOfMeasure='1/Month',price='19.71')
        p=self.pricing([dict(good,productName='Premium Page Blob'),dict(good,meterName='P10 LRS Disk Mount'),good])
        self.assertEqual(p.rate(item)['monthly'],Decimal('19.71'))
    def test_pagination_and_ambiguity(self):
        calls=[]
        def transport(url,timeout):
            calls.append(url)
            return {'Items':[],'NextPageLink':c.API+'?page=2'} if len(calls)==1 else {'Items':[meter()]}
        p=self.pricing(transport=transport)
        p.rate(c.spec('azurerm_linux_virtual_machine',vm()))
        self.assertEqual(p.calls,2)
        p.clear()
        q=self.pricing([meter(),meter(meterId='other')])
        with self.assertRaises(c.Unpriced):q.rate(c.spec('azurerm_linux_virtual_machine',vm()))
    def test_no_partial_update_savings(self):
        p=self.pricing()
        rows,warnings,_=self.analyze(p,resource(['update'],vm(),vm('Unknown')))
        self.assertIsNone(rows[0]['delta']); self.assertTrue(warnings)
    def test_network_offline_and_unknown(self):
        def fail(*_):raise OSError('network down')
        p=self.pricing(transport=fail)
        rows,warnings,_=self.analyze(p,resource(['create'],None,vm()))
        self.assertTrue(warnings); self.assertIsNone(rows[0]['new'])
        self.assertEqual(p.db.execute('SELECT count(*) FROM pricing_cache').fetchone()[0],0)
        q=self.pricing(offline=True)
        with self.assertRaises(c.Unpriced):q.rate(c.spec('azurerm_linux_virtual_machine',vm()))
        self.assertEqual(q.calls,0)
    def test_transient_timeout_retries_then_caches(self):
        attempts=[]
        def flaky(url,timeout):
            attempts.append(url)
            if len(attempts)<3:
                raise TimeoutError('timed out')
            return {'Items':[meter()], 'NextPageLink':None}
        p=self.pricing(transport=flaky,retries=2)
        with patch.object(c.time,'sleep'):
            price=p.rate(c.spec('azurerm_linux_virtual_machine',vm()))
        self.assertEqual(price['monthly'],Decimal('7.30'))
        self.assertEqual((len(attempts),p.calls),(3,3))
        self.assertEqual(p.rate(c.spec('azurerm_linux_virtual_machine',vm()))['source'],'cache')
    def test_no_retry_for_missing_meter(self):
        attempts=[]
        def empty(url,timeout):
            attempts.append(url)
            return {'Items':[], 'NextPageLink':None}
        p=self.pricing(transport=empty)
        with self.assertRaises(c.Unpriced):
            p.rate(c.spec('azurerm_linux_virtual_machine',vm()))
        self.assertEqual(len(attempts),1)
    def test_unknown_after_and_noise(self):
        p=self.pricing(transport=lambda *_:self.fail('Unexpected API call'))
        rows,warnings,_=self.analyze(p,resource(['create'],None,vm(),after_unknown={'size':True}))
        self.assertTrue(warnings)
        noise=dict(resource(['create'],None,{}),type='azurerm_subnet')
        self.assertEqual(self.analyze(p,noise),([],[],1))
    def test_policy_exact_boundary_and_strict(self):
        p=self.pricing(); rows,warnings,skipped=self.analyze(p,resource(['create'],None,vm()))
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(c.render(rows,[],0,p,Decimal('7.30')),0)
            self.assertEqual(c.render(rows,[],0,p,Decimal('7.29')),1)
            self.assertEqual(c.render([],['unknown'],0,p,Decimal('50'),strict=True),2)
    def test_invalid_json_missing_file_and_nan(self):
        path=self.folder/'bad.json'; path.write_text('{bad')
        with contextlib.redirect_stderr(io.StringIO()):
            for args in [['--plan',str(path)],['--plan',str(path)+'missing'],['--max-increase','NaN']]:
                self.assertEqual(c.main(args+['--cache',str(self.path)]),2)
    def test_stdin_and_file_equivalence(self):
        plan={'resource_changes':[]}; path=self.folder/'plan.json'; path.write_text(json.dumps(plan))
        with contextlib.redirect_stdout(io.StringIO()), patch('sys.stdin',io.StringIO(json.dumps(plan))):
            self.assertEqual(c.main(['--cache',str(self.path)]),0)
            self.assertEqual(c.main(['--cache',str(self.path),'--plan',str(path)]),0)
    def test_terraform_output_only_plan(self):
        self.assertEqual(c.analyze({'format_version':'1.2','planned_values':{'outputs':{}}},self.pricing()),([],[],0))
    def test_malformed_structure(self):
        p=self.pricing()
        for plan in [[],{}, {'resource_changes':{}}, {'resource_changes':[None]},
                     {'resource_changes':[resource(['unexpected'],vm(),vm())]}]:
            with self.assertRaises(ValueError):c.analyze(plan,p)
    def test_malformed_state_warns(self):
        rows,warnings,_=self.analyze(self.pricing(),resource(['create'],None,['bad']))
        self.assertTrue(warnings); self.assertIsNone(rows[0]['delta'])


if __name__=='__main__':unittest.main()

import json
import threading
import unittest
import uuid
from decimal import Decimal
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from web import server


class WebTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'tmp'/'tests'
        root.mkdir(parents=True,exist_ok=True)
        self.folder=root/uuid.uuid4().hex
        self.folder.mkdir()
        self.cache=self.folder/'cache.db'

    def tearDown(self):
        assert self.folder.resolve().is_relative_to(Path(__file__).resolve().parents[1]/'tmp'/'tests')
        for file in self.folder.iterdir():
            file.unlink()
        self.folder.rmdir()

    def test_sample_uses_live_price_and_then_cache(self):
        calls=[]
        def fake(url,timeout):
            calls.append(url)
            sku='Standard_B2s' if 'Standard_B2s' in url else 'Standard_B1s'
            return {'Items':[dict(currencyCode='USD',tierMinimumUnits=0,retailPrice='0.01',
                                  armRegionName='eastus',meterId=sku,meterName=sku,
                                  productName='Virtual Machines BS Series',serviceName='Virtual Machines',
                                  unitOfMeasure='1 Hour',type='Consumption',armSkuName=sku)],
                    'NextPageLink':None}
        request=dict(source='sample',sample='01-create',max_increase='5',currency='USD')
        first=server.evaluate(request,transport=fake,cache=self.cache)
        self.assertEqual((first['status'],first['exit_code'],first['api_calls']),('FAILED',1,1))
        self.assertEqual(first['delta'],Decimal('7.30'))
        request['offline']=True
        second=server.evaluate(request,transport=lambda *_:self.fail('network used'),cache=self.cache)
        self.assertEqual((second['cache_hits'],second['api_calls']),(1,0))
        self.assertEqual(len(calls),1)

    def test_upload_and_invalid_budget(self):
        plan={'resource_changes':[]}
        result=server.evaluate(dict(source='upload',plan=plan,max_increase='20',currency='USD'),cache=self.cache)
        self.assertEqual(result['status'],'PASSED')
        with self.assertRaises(ValueError):
            server.evaluate(dict(source='upload',plan=plan,max_increase='-1'),cache=self.cache)
        with self.assertRaises(ValueError):
            server.evaluate(dict(source='sample',sample='../unknown'),cache=self.cache)

    def test_local_http_page_and_analyze(self):
        http=HTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True)
        thread.start()
        base=f'http://127.0.0.1:{http.server_port}'
        try:
            with urlopen(base+'/') as response:
                page=response.read().decode()
            self.assertIn('Know the cost before you deploy',page)
            body=json.dumps(dict(source='sample',sample='04-hostile-noise',max_increase='20')).encode()
            request=Request(base+'/api/analyze',data=body,headers={'Content-Type':'application/json'})
            with urlopen(request) as response:
                result=json.load(response)
            self.assertEqual((result['status'],result['skipped'],result['api_calls']),('PASSED',15,0))
            bad=Request(base+'/api/analyze',data=body,headers={'Origin':'https://elsewhere.example'})
            with self.assertRaises(HTTPError) as context:
                urlopen(bad)
            self.assertEqual(context.exception.code,403)
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=2)


if __name__=='__main__':
    unittest.main()

"""Exercise plans emitted by Terraform's AzureRM provider mock test runs."""
import json
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

import costguard


ROOT = Path(__file__).resolve().parents[1]


def transport(url, timeout):
    query = unquote(url)
    if 'Storage' in query:
        item = dict(serviceName='Storage', productName='Premium SSD Managed Disks',
                    meterName='P10 LRS Disk', armSkuName='P10 LRS',
                    unitOfMeasure='1/Month', retailPrice=19.71, meterId='p10')
    else:
        sku = 'Standard_B2s' if 'Standard_B2s' in query else 'Standard_B1s'
        item = dict(serviceName='Virtual Machines', productName='Virtual Machines BS Series',
                    meterName=sku, armSkuName=sku, unitOfMeasure='1 Hour',
                    retailPrice=0.04 if sku == 'Standard_B2s' else 0.01, meterId=sku)
    item.update(type='Consumption', currencyCode='USD', armRegionName='eastus',
                effectiveStartDate='2025-01-01T00:00:00Z')
    return {'Items': [item], 'NextPageLink': None}


class TerraformPlansTests(unittest.TestCase):
    def test_create_upgrade_delete_from_terraform(self):
        folder = ROOT / 'tmp' / 'tests'
        folder.mkdir(parents=True, exist_ok=True)
        cache = folder / ('terraform-' + uuid.uuid4().hex + '.db')
        pricing = costguard.Pricing(cache, transport=transport)
        try:
            for name, action, expected, count in (
                ('create', 'CREATE', Decimal('27.01'), 2),
                ('upgrade', 'UPDATE', Decimal('21.90'), 1),
                ('delete', 'DELETE', Decimal('-7.30'), 1),
            ):
                plan = json.loads((ROOT / 'test-plans' / f'terraform-azure-{name}.json').read_text())
                self.assertIn('Terraform test', plan['origin'])
                rows, warnings, skipped = costguard.analyze(plan, pricing)
                self.assertFalse(warnings, name)
                self.assertEqual(sum((r['delta'] for r in rows), Decimal(0)), expected, name)
                self.assertEqual(len(rows), count, name)
                self.assertEqual(rows[0]['action'], action, name)
                self.assertGreaterEqual(skipped, 1, name)
        finally:
            pricing.db.close()
            cache.unlink(missing_ok=True)

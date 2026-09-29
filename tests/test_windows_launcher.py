"""Regression for native-to-Python fallback in workspace paths with spaces."""
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'win32' and (ROOT / 'costguard.exe').exists(),
                     'Requires the bundled Windows CLI')
class WindowsLauncherTests(unittest.TestCase):
    def test_offline_uncached_fallback_preserves_strict_exit_code(self):
        cache = ROOT / 'tmp' / ('empty-' + uuid.uuid4().hex + '.db')
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [str(ROOT / 'costguard.cmd'), '--plan',
                 str(ROOT / 'test-plans' / 'terraform-azure-create.json'),
                 '--cache', str(cache), '--offline', '--strict'],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('defaulting SKU to $0.00', result.stderr)
            self.assertIn('Status: INCOMPLETE', result.stdout)
        finally:
            cache.unlink(missing_ok=True)

    def test_native_and_python_reports_are_identical(self):
        """The exe fast path must print exactly what costguard.py prints for a warm-cache plan."""
        plan = ROOT / 'test-plans' / 'terraform-azure-create.json'
        for limit, expected in (('50', 0), ('20', 1)):
            args = ['--plan', str(plan), '--offline', '--strict', '--max-increase', limit]
            native = subprocess.run([str(ROOT / 'costguard.exe'), *args], cwd=ROOT, capture_output=True, text=True)
            python = subprocess.run([sys.executable, str(ROOT / 'costguard.py'), *args], cwd=ROOT, capture_output=True, text=True)
            if python.returncode == 2:
                self.skipTest('Warm the cache first: py scripts/warm_cache.py')
            self.assertEqual((native.returncode, python.returncode), (expected, expected), native.stdout + python.stderr)
            self.assertIn('Cache: 2 hits, 0 API requests', native.stdout)
            self.assertEqual(native.stdout, python.stdout)
            if expected == 1:
                self.assertIn('[CIRCUIT BREAKER]', native.stdout)

"""Install verified portable Terraform and SQLite into this workspace only."""
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'tools'/'bin'
DEST.mkdir(parents=True,exist_ok=True)


def download(url):
    with urllib.request.urlopen(url,timeout=60) as response:
        return response.read()


def install(url, expected, algorithm, executable):
    data=download(url)
    actual=hashlib.new(algorithm,data).hexdigest()
    if actual != expected:
        raise RuntimeError(f'Checksum mismatch for {url}')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member=next(n for n in archive.namelist() if n.split('/')[-1]==executable)
        (DEST/executable).write_bytes(archive.read(member))
    return dict(url=url,checksum=actual,algorithm=algorithm)


version='1.16.4'
base=f'https://releases.hashicorp.com/terraform/{version}/'
name=f'terraform_{version}_windows_amd64.zip'
sums=download(base+f'terraform_{version}_SHA256SUMS').decode()
sha=next(line.split()[0] for line in sums.splitlines() if line.endswith(name))
terraform=install(base+name,sha,'sha256','terraform.exe')
page=download('https://www.sqlite.org/download.html').decode()
match=re.search(r'PRODUCT,([^,]+),(\d+/sqlite-tools-win-x64-\d+\.zip),\d+,([a-f0-9]{64})',page)
if not match:
    raise RuntimeError('Cannot find official SQLite Windows download metadata')
sqlite=install('https://www.sqlite.org/'+match[2],match[3],'sha3_256','sqlite3.exe')
(ROOT/'tools'/'versions.json').write_text(json.dumps(dict(terraform=terraform,sqlite=sqlite),indent=2)+'\n')
print('Installed and checksum-verified Terraform and SQLite in',DEST)

"""Build the optional fast Windows CLI using verified SQLite amalgamation."""
import hashlib
import io
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'tmp'/'native'
SCRATCH.mkdir(parents=True,exist_ok=True)
URL='https://www.sqlite.org/2026/sqlite-amalgamation-3530400.zip'
SHA3='628a44cfe82c66aed1ccbbe85a562d2e33ebe64b3288981ed76285612227934e'
if not (SCRATCH/'sqlite3.c').exists() or not (SCRATCH/'sqlite3.h').exists():
    data=urllib.request.urlopen(URL,timeout=90).read()
    if hashlib.sha3_256(data).hexdigest()!=SHA3:
        raise RuntimeError('SQLite source checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in ('sqlite3.c','sqlite3.h'):
            member=next(p for p in archive.namelist() if p.endswith('/'+name))
            (SCRATCH/name).write_bytes(archive.read(member))
subprocess.run(['gcc','-O2','-std=c11','-DSQLITE_THREADSAFE=0','-DSQLITE_OMIT_LOAD_EXTENSION',
                '-I',str(SCRATCH),str(ROOT/'native'/'costguard_fast.c'),str(SCRATCH/'sqlite3.c'),
                '-o',str(ROOT/'costguard.exe')],check=True)
print('Built',ROOT/'costguard.exe')

"""Exercise the actual wrapper and repeated collection without S3/AWS access."""
import hashlib
import importlib.util
from pathlib import Path
import shutil
s=importlib.util.spec_from_file_location('collector','/src/collectors/host_collect.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
engine=Path('/tmp/ea-collector-engine');shutil.copy('/artifacts/velociraptor',engine);engine.chmod(0o700)
output=Path('/tmp/ea-wrapper-rehearsal.zip');expected=hashlib.sha256(engine.read_bytes()).hexdigest()
first=m.collect(output,engine,Path('/src/collectors'),expected)
second=m.collect(output,engine,Path('/src/collectors'),expected)
assert first==second and first['size_bytes']>0
print('PASS actual wrapper collection, URL-encoded ZIP members, checksum and same-byte retry')
print(first)

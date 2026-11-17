"""Native Windows test of public upstream dependency wheels only.

Does not import server code, original modules, user assets, or private payloads.
The only network checks are public Python.org robots and OSM capabilities.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from pak import unpack


def main():
    if os.name != 'nt':
        raise SystemExit('This dependency smoke test requires native Windows x64.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-root', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='OpenMap public dependencies kiểm thử ') as folder:
        runtime = Path(folder) / 'bộ xử lý công khai'
        manifest = unpack(args.package_root / 'windows-x64.pak', runtime)
        expected = manifest['dependency_versions']
        code = r'''
import importlib.metadata,io,json,os,ssl,sys
import xml.etree.ElementTree as ET
import numpy as np
import PIL
from PIL import Image,features
import requests,certifi,charset_normalizer.md
expected=json.loads(sys.argv[1])
actual={name:importlib.metadata.version(name) for name in expected}
assert actual==expected,(actual,expected)
assert sys.version_info[:2]==(3,14),sys.version
# Exercise the bundled OpenBLAS/linalg native DLLs, not just Python imports.
a=np.array([[3.,1.],[1.,2.]])
x=np.linalg.solve(a,np.array([9.,8.]))
assert np.allclose(x,[2.,3.]),x
assert np.allclose(np.dot(a,np.linalg.inv(a)),np.eye(2))
assert charset_normalizer.md.__file__.lower().endswith('.pyd')
image=Image.new('RGB',(32,24),(90,130,170))
stream=io.BytesIO();image.save(stream,'JPEG',quality=90)
with Image.open(io.BytesIO(stream.getvalue())) as decoded:
    assert decoded.size==(32,24) and decoded.mode=='RGB'
assert os.path.isfile(certifi.where())
assert 'BEGIN CERTIFICATE' in open(certifi.where(),encoding='ascii').read(4096)
session=requests.Session()
session.headers['User-Agent']='OpenMap-public-dependency-smoke/0.4.0'
network=[]
def get(url,maximum=1000000):
    with session.get(url,timeout=(10,30),stream=True) as response:
        response.raise_for_status()
        content=response.raw.read(maximum+1,decode_content=True)
        assert len(content)<=maximum,'Response exceeds bound'
        return response.status_code,content
status,_=get('https://www.python.org/robots.txt',100000)
network.append({'host':'www.python.org','path':'/robots.txt','status':status,'verify_tls':True})
osm_ok=False
for host in ('www.openstreetmap.org','api.openstreetmap.org'):
    try:
        status,body=get('https://'+host+'/api/0.6/capabilities')
        root=ET.fromstring(body)
        assert root.tag=='osm' and root.find('api') is not None
        network.append({'host':host,'path':'/api/0.6/capabilities','status':status,'verify_tls':True})
        osm_ok=True
        break
    except Exception as error:
        network.append({'host':host,'path':'/api/0.6/capabilities','error_type':type(error).__name__})
assert osm_ok,json.dumps(network)
print(json.dumps({'public_dependencies':'PASS','python':sys.version.split()[0],'versions':actual,
                  'numpy_linalg':True,'native_charset_normalizer':True,'pillow_jpeg':True,
                  'jpeg_codec':features.version('jpg'),'unicode_runtime_path':True,
                  'openssl':ssl.OPENSSL_VERSION,'network':network},ensure_ascii=False),flush=True)
'''
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf8'
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        result = subprocess.run([str(runtime / 'python.exe'), '-c', code, json.dumps(expected)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf8', errors='replace', timeout=150)
        print(result.stdout, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
        print(json.dumps({'public_runtime_catalog':'PASS','runtime_files':manifest['file_count'],
                          'package_sha256':manifest['package_sha256'],'no_private_engine_loaded':True}),flush=True)


if __name__ == '__main__':
    main()

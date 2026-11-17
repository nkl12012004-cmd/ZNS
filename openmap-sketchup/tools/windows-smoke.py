"""Native Windows validation of the packaged CPython, Pillow, OCR and Ruby boot."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

from pak import unpack

ROOT = Path(__file__).resolve().parents[1]


def run(argv, **kwargs):
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf8', errors='replace', timeout=240, **kwargs)
    print(result.stdout, flush=True)
    if result.returncode: raise RuntimeError('Native command failed: '+str(result.returncode))


def main():
    if os.name != 'nt': raise SystemExit('This test must run on native Windows x64.')
    with tempfile.TemporaryDirectory(prefix='OpenMap bản đầy đủ ') as folder:
        path = Path(folder)
        rbz = next((ROOT/'dist').glob('OpenMap_SketchUp_Full_0.2.2_Windows_x64.rbz'))
        installed = path/'SketchUp Plugins thử nghiệm'
        with zipfile.ZipFile(rbz) as archive: archive.extractall(installed)
        plugin = installed/'openmap_sketchup'
        engine = path/'runtime kiểm tra'
        manifest = unpack(plugin/'runtime/windows-x64.pak', engine)
        python = str(engine/'python.exe')
        env = {**os.environ, 'PYTHONIOENCODING':'utf8'}
        for name in ('OPENMAP_LOCAL_TOKEN','OPENMAP_OCR_DIR','OPENMAP_CONFIG_FILE','SUPABASE_URL','SUPABASE_ANON_KEY'): env.pop(name,None)
        code = 'import sys,unittest;sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2]);r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(sys.argv[2]));sys.exit(0 if r.wasSuccessful() else 1)'
        run([python,'-c',code,str(plugin/'server'),str(ROOT/'server/tests')],env=env)
        native_code = r'''
import base64,io,json,sys,urllib.request
sys.path.insert(0,sys.argv[1])
from PIL import Image,ImageDraw,ImageFont
from openmap_server import ocr,native_ocr
image=Image.new('RGB',(1900,150),'white')
ImageDraw.Draw(image).text((25,25),'10.776889, 106.700806',fill='black',font=ImageFont.load_default(size=64))
output=io.BytesIO();image.save(output,'PNG')
text=ocr.recognize({'image':base64.b64encode(output.getvalue()).decode()})['text']
assert '10.776' in text and '106.700' in text,text
dll,_=native_ocr.library()
print(json.dumps({'native_ocr':'PASS','tesseract':dll.TessVersion().decode(),'recognized':text.strip(),'unicode_paths':True}))
with urllib.request.urlopen('https://www.python.org/robots.txt',timeout=30) as response: assert response.status==200
print('Bundled HTTPS/OpenSSL: PASS')
'''
        run([python,'-c',native_code,str(plugin/'server')],env={**env,'OPENMAP_OCR_DIR':str(engine/'ocr')})
        run(['ruby',str(ROOT/'tools/runtime-smoke.rb'),str(plugin)],env=env)
        probe = path/'parent-probe.json'
        run(['ruby',str(ROOT/'tools/runtime-smoke.rb'),str(plugin),'--parent-exit'],env={**env,'OPENMAP_PARENT_PROBE':str(probe)})
        data=json.loads(probe.read_text(encoding="utf8"))
        port=int(data['url'].rsplit(':',1)[1])
        closed=False
        for _ in range(40):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2): pass
            except OSError:
                closed=True;break
            time.sleep(.25)
        if not closed: raise RuntimeError('Worker survived the parent process exit')
        shutil.rmtree(Path(data['state_root']).parent,ignore_errors=True)
        print(json.dumps({'windows_full':'PASS','python':manifest['python_version'],'pillow':manifest['pillow_version'],'runtime_files':manifest['file_count'],'parent_exit_cleanup':True}),flush=True)


if __name__=='__main__': main()

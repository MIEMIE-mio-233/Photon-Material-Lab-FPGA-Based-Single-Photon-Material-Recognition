import subprocess,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];tests=ROOT/'src/ps/tests'
subprocess.run([sys.executable,'-m','unittest','discover','-s',str(tests),'-p','test_*.py'],check=True)
node=shutil.which('node')
if node:
    for path in sorted(tests.glob('test_*.js')):subprocess.run([node,str(path)],check=True)
else:print('SKIP: Node.js未安装，前端检查未运行')

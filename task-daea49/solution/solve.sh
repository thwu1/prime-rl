#!/bin/bash

pip3 install cryptography==43.0.1 -q

# Fix Go implementation bugs (5 bugs in xaes.go)
python3 /solution/fix_go.py

# Install correct Python XAES-256-GCM implementation (replaces buggy partial code)
python3 -c "
import shutil
shutil.copy('/solution/xaes256gcm_correct.py', '/app/py_impl/xaes256gcm.py')
print('Python XAES-256-GCM implementation installed.')
"

# Create file encryption tool
python3 -c "
import os, shutil
os.makedirs('/app/file_tool', exist_ok=True)
shutil.copy('/solution/xaes_file.py', '/app/file_tool/xaes_file.py')
print('File encryption tool installed.')
"

echo "All fixes and implementations applied."

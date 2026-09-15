#!/bin/bash

# Fix multi-line attribute formatting in WGSL shaders.
# The parser processes line-by-line and silently drops @align/@size
# attributes that appear on a separate line from the member declaration.
python3 -c "
import re, glob
for path in glob.glob('/app/shaders/*.wgsl'):
    with open(path) as f:
        content = f.read()
    content = re.sub(r'(@(?:align|size)\(\d+\))\s*\n\s*', r'\1 ', content)
    with open(path, 'w') as f:
        f.write(content)
print('Normalized multi-line attributes in WGSL shaders')
"

# Install the complete code generator and bridge driver
cp /solution/c_codegen_fixed.py /app/c_codegen.py
cp /solution/bridge.py /app/bridge.py

# Run the bridge pipeline
cd /app && python3 /app/bridge.py

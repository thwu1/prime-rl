#!/usr/bin/env bash

# Install the complete codec implementation
cp /solution/codec.py /app/codec.py
chmod +x /app/codec.py

echo "Codec installed at /app/codec.py"
python3 -c "
import json, subprocess, tempfile, os

# Quick smoke test: encode then decode a simple frame
scenario = {
    'table': {
        'timestamp': None,
        'entries': {'0': {'tag': 'Info', 'format': 'Hello, world!'}}
    },
    'logs': [{'index': 0, 'values': []}]
}
fd, fname = tempfile.mkstemp(suffix='.json', dir='/tmp')
with os.fdopen(fd, 'w') as f:
    json.dump(scenario, f)

enc = subprocess.run(['python3', '/app/codec.py', 'encode', fname],
                     capture_output=True, text=True)
assert enc.returncode == 0, f'Encode failed: {enc.stderr}'
hex_frame = enc.stdout.strip()
assert hex_frame == '0000', f'Unexpected: {hex_frame}'

dec_scenario = {
    'table': scenario['table'],
    'frames': [hex_frame]
}
fd2, fname2 = tempfile.mkstemp(suffix='.json', dir='/tmp')
with os.fdopen(fd2, 'w') as f:
    json.dump(dec_scenario, f)

dec = subprocess.run(['python3', '/app/codec.py', 'decode', fname2],
                     capture_output=True, text=True)
assert dec.returncode == 0, f'Decode failed: {dec.stderr}'
assert 'Hello, world!' in dec.stdout, f'Unexpected: {dec.stdout}'

os.unlink(fname)
os.unlink(fname2)
print('Smoke test passed.')
"

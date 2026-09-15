#!/bin/bash

cp /solution/crdt_impl.py /app/yjs_compat.py

cd /app
python3 -c "
from yjs_compat import YDoc
import subprocess, json, tempfile, os

# Verify basic decode from fixture
doc = YDoc(999)
with open('/app/fixtures/basic_hello.bin', 'rb') as f:
    doc.apply_update_v1(f.read())
assert str(doc.get_text('t')) == 'hello', f'Decode failed: {str(doc.get_text(\"t\"))}'

# Verify encode accepted by Yjs
doc2 = YDoc(1)
doc2.get_text('t').insert(0, 'test')
data = doc2.encode_state_as_update_v1()
with tempfile.NamedTemporaryFile(suffix='.bin', dir='/tmp', delete=False) as f:
    f.write(data)
    tmp = f.name
result = subprocess.run(['node', '/app/yjs_oracle.js', 'apply', 't', tmp],
    capture_output=True, text=True, timeout=30)
os.unlink(tmp)
out = json.loads(result.stdout)
assert out['text'] == 'test', f'Encode failed: {out}'

# Verify conflict resolution matches Yjs
doc3 = YDoc(998)
with open('/app/fixtures/client_a.bin', 'rb') as f:
    doc3.apply_update_v1(f.read())
with open('/app/fixtures/client_b.bin', 'rb') as f:
    doc3.apply_update_v1(f.read())
result = subprocess.run(['node', '/app/yjs_oracle.js', 'apply', 't',
    '/app/fixtures/client_a.bin', '/app/fixtures/client_b.bin'],
    capture_output=True, text=True, timeout=30)
yjs_text = json.loads(result.stdout)['text']
assert str(doc3.get_text('t')) == yjs_text, f'Convergence: py={str(doc3.get_text(\"t\"))} js={yjs_text}'

# Verify snapshots survive insert-after-delete
doc4 = YDoc(700)
doc4.get_text('t').insert(0, 'hello world')
snap1 = doc4.snapshot()
doc4.get_text('t').delete(5, 6)
doc4.get_text('t').insert(5, '!')
assert str(doc4.get_text('t')) == 'hello!', f'Text after edit: {str(doc4.get_text(\"t\"))}'
assert doc4.text_at_snapshot('t', snap1) == 'hello world', f'Snapshot: {doc4.text_at_snapshot(\"t\", snap1)}'

print('All solution verifications passed')
"

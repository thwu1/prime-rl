#!/bin/bash

# Deploy the KV store implementation
cp /solution/kvstore_impl.py /app/kvstore.py

# Verify the solution works
cd /app
python3 -c "
import sys
sys.path.insert(0, '/app')
from flash_sim import FlashSimulator
from kvstore import FlashKVStore

# Basic functional self-test
flash = FlashSimulator(4 * 4096)
store = FlashKVStore(flash)
store.format()

# CRUD
store.put(b'hello', b'world')
assert store.get(b'hello') == b'world', 'basic put/get failed'

store.put(b'hello', b'earth')
assert store.get(b'hello') == b'earth', 'overwrite failed'

assert store.delete(b'hello') is True, 'delete failed'
assert store.get(b'hello') is None, 'get after delete failed'

# Recovery
store.put(b'persist', b'data')
raw = flash.get_raw()
flash2 = FlashSimulator(4 * 4096)
flash2.load_raw(raw)
store2 = FlashKVStore(flash2)
assert store2.get(b'persist') == b'data', 'recovery failed'

# Cross-compatibility with C tool
import subprocess, tempfile, os
tmp = tempfile.NamedTemporaryFile(suffix='.bin', delete=False)
tmp.write(flash.get_raw())
tmp.close()
r = subprocess.run(['/app/tickv_ref/tickv_tool', 'get', tmp.name, 'persist'],
                   capture_output=True, text=True)
assert r.stdout.strip() == 'data', 'C tool cross-read failed'
os.unlink(tmp.name)

# Compaction
store.put(b'a', b'1')
store.put(b'b', b'2')
store.put(b'a', b'11')  # overwrite to create dead entry
store.compact()
assert store.get(b'a') == b'11', 'post-compact get failed'
assert store.get(b'b') == b'2', 'post-compact get failed'
assert store.get(b'persist') == b'data', 'post-compact get failed'

# Wear-leveling: verify page with lowest EC is chosen
flash3 = FlashSimulator(4 * 4096)
for _ in range(10):
    flash3.erase_page(1)
store3 = FlashKVStore(flash3)
store3.format()
val = b'X' * (4096 - 12 - 16 - 1)
store3.put(b'a', val)
store3.put(b'b', b'switch')
# Page 3 should be active (lowest EC among free pages)
for pn in range(flash3.num_pages):
    base = pn * flash3.page_size
    if flash3.read(base, 4) == b'\\x54\\x4b\\x56\\x31':
        if flash3.read(base + 4, 1)[0] == 0x0F:
            assert pn in (2, 3), f'Wear-leveling failed: active page {pn}'
            break

print('All solution self-tests passed')
"

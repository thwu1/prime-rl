#!/bin/bash


cd /app

# Install npm dependencies
npm install 2>&1

# Verify source files exist
for f in parse-update.ts write-update.ts delete-set.ts merge-updates.ts state-vector.ts cli.ts; do
  if [ ! -f "/app/src/$f" ]; then
    echo "ERROR: /app/src/$f not found"
    ls -la /app/src/ 2>&1 || echo "/app/src/ does not exist"
    exit 1
  fi
done

# ---------------------------------------------------------------
# Fix Bug 1: parse-update.ts
# The hasOrigin and hasRightOrigin flag bit masks are swapped.
# Bit 0 should indicate hasOrigin; bit 1 should indicate hasRightOrigin.
# ---------------------------------------------------------------
python3 -c "
import sys
with open('/app/src/parse-update.ts', 'r') as f:
    content = f.read()
content = content.replace(
    'const hasOrigin = (flags & 0x02) !== 0;',
    'const hasOrigin = (flags & 0x01) !== 0;  // fixed: bit 0'
)
content = content.replace(
    'const hasRightOrigin = (flags & 0x01) !== 0;',
    'const hasRightOrigin = (flags & 0x02) !== 0;  // fixed: bit 1'
)
with open('/app/src/parse-update.ts', 'w') as f:
    f.write(content)
print('Fixed parse-update.ts')
"

# ---------------------------------------------------------------
# Fix Bug 2: write-update.ts
# Client IDs must be sorted in descending order (highest first).
# ---------------------------------------------------------------
python3 -c "
with open('/app/src/write-update.ts', 'r') as f:
    content = f.read()
content = content.replace(
    'clientIDs.sort((a, b) => a - b);',
    'clientIDs.sort((a, b) => b - a);  // fixed: descending order'
)
with open('/app/src/write-update.ts', 'w') as f:
    f.write(content)
print('Fixed write-update.ts')
"

# ---------------------------------------------------------------
# Fix Bug 3: delete-set.ts
# Adjacent ranges (where prevEnd == curr.clock) must also be merged.
# ---------------------------------------------------------------
python3 -c "
with open('/app/src/delete-set.ts', 'r') as f:
    content = f.read()
content = content.replace(
    'if (prevEnd > curr.clock) {',
    'if (prevEnd >= curr.clock) {  // fixed: merge adjacent ranges too'
)
with open('/app/src/delete-set.ts', 'w') as f:
    f.write(content)
print('Fixed delete-set.ts')
"

# ---------------------------------------------------------------
# Fix Bug 4: merge-updates.ts
# Replace the stub implementation with the complete merge function.
# ---------------------------------------------------------------
cp /solution/merge-updates-fixed.ts /app/src/merge-updates.ts
echo "Fixed merge-updates.ts"

# ---------------------------------------------------------------
# Fix Bug 5: state-vector.ts
# computeStateVector: off-by-one (clock + length - 1 -> clock + length)
# diffUpdate: boundary check (clock >= -> clock + length >)
# ---------------------------------------------------------------
python3 -c "
with open('/app/src/state-vector.ts', 'r') as f:
    content = f.read()
content = content.replace(
    'const end = struct.id.clock + struct.length - 1;',
    'const end = struct.id.clock + struct.length;  // fixed: next expected clock'
)
content = content.replace(
    'const missing = structs.filter(s => s.id.clock >= remoteClock);',
    'const missing = structs.filter(s => s.id.clock + s.length > remoteClock);  // fixed: boundary'
)
with open('/app/src/state-vector.ts', 'w') as f:
    f.write(content)
print('Fixed state-vector.ts')
"

# ---------------------------------------------------------------
# Fix Bug 6: cli.ts
# readBinaryFile uses utf-8 encoding which corrupts binary data.
# Must read as raw Buffer without text encoding.
# ---------------------------------------------------------------
python3 -c "
with open('/app/src/cli.ts', 'r') as f:
    content = f.read()
content = content.replace(
    \"const content = fs.readFileSync(path, 'utf-8');\",
    '// fixed: read as raw binary buffer'
)
content = content.replace(
    \"return new Uint8Array(Buffer.from(content, 'utf-8'));\",
    'return new Uint8Array(fs.readFileSync(path));'
)
with open('/app/src/cli.ts', 'w') as f:
    f.write(content)
print('Fixed cli.ts')
"

echo "All fixes applied"
exit 0

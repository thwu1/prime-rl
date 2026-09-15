#!/bin/bash

# Phase 1: Repair the pack file's corrupted SHA-1 checksum
# The trailing 20 bytes of the .pack file have been zeroed out.
# We compute SHA-1 of all bytes except the trailing 20 and patch in-place.
PACK_DIR="/app/repo/.git/objects/pack"
PACK_FILE=$(ls "$PACK_DIR"/*.pack | head -1)

python3 -c "
import hashlib
import sys
pack_path = sys.argv[1]
with open(pack_path, 'r+b') as f:
    data = f.read()
    correct_checksum = hashlib.sha1(data[:-20]).digest()
    f.seek(-20, 2)
    f.write(correct_checksum)
print('Pack checksum repaired: ' + correct_checksum.hex())
" "$PACK_FILE"

# Phase 2: Deploy the pack parser and rebuild the index
cp /solution/pack_parser.py /app/packparse.py
python3 /app/packparse.py /app/repo/.git --rebuild-index

# Phase 3: Generate the verification report using git verify-pack
IDX_FILE=$(ls "$PACK_DIR"/*.idx | head -1)
git -C /app/repo verify-pack -v "$IDX_FILE" > /app/verify_report.txt 2>&1
echo "Verification report written to /app/verify_report.txt"

# Phase 4: Create recovery bundle with all branches
cd /app/repo
git bundle create /app/recovered.bundle --all
echo "Recovery bundle created at /app/recovered.bundle"

# Validate the bundle
git bundle verify /app/recovered.bundle
echo "Recovery complete"

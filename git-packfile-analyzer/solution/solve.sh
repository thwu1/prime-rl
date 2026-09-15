#!/bin/bash

cd /app/repo

# Step 1: Fix HEAD — currently points to non-existent refs/heads/main
echo "ref: refs/heads/master" > .git/HEAD

# Step 2: Remove spurious shallow file
rm -f .git/shallow

# Step 3: Repair packfile (version + checksum)
python3 /solution/fix_pack.py

# Step 4: Regenerate pack index
PACK_FILE=$(ls .git/objects/pack/*.pack)
git index-pack "$PACK_FILE"

# Step 5: Fix corrupted feature/string-utils branch ref
python3 /solution/fix_refs.py

# Step 6: Write diagnosis report
python3 /solution/write_diagnosis.py

# Verify repairs
echo "=== Verification ==="
git fsck --full 2>&1
echo "fsck exit: $?"
git log --all --oneline
git verify-pack -v .git/objects/pack/*.idx > /dev/null 2>&1
echo "verify-pack exit: $?"
echo "=== Done ==="

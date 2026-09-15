#!/bin/bash

cd /app/repo

# === Fix 1: Repository config ===
# The config has repositoryformatversion=1 with an unknown required extension
# "nonstandardCapability", which causes ALL git operations to fail.
# We must edit .git/config directly since git commands don't work yet.
python3 -c "
import re
with open('.git/config') as f:
    content = f.read()
content = re.sub(r'\[extensions\][^\[]*', '', content)
content = content.replace('repositoryformatversion = 1', 'repositoryformatversion = 0')
with open('.git/config', 'w') as f:
    f.write(content)
"
echo "Fix 1: Config repaired — removed unknown extension, reset format version"

# Verify git recognizes the repo now
git -C /app/repo rev-parse --git-dir >/dev/null 2>&1 || { echo "ERROR: config fix failed"; exit 1; }

# === Fix 2: Generate pack index ===
# The .idx file is missing and git-index-pack has been disabled.
# Deploy our custom pack index generator.
cp /solution/pack_index_gen.py /app/pack_index_gen.py
chmod +x /app/pack_index_gen.py

PACK_FILE=$(ls .git/objects/pack/*.pack)
python3 /app/pack_index_gen.py "$PACK_FILE" || { echo "ERROR: pack index generation failed"; exit 1; }
echo "Fix 2: Pack index generated"

# === Fix 3: Fix branch ref ===
# A bogus loose ref (all zeros) was placed in refs/heads/, overriding the
# correct entry in packed-refs. Remove it so git falls back to packed-refs.
BRANCH=$(sed 's|ref: refs/heads/||' < .git/HEAD)
if [ -f ".git/refs/heads/$BRANCH" ]; then
    CURRENT_SHA=$(cat ".git/refs/heads/$BRANCH")
    if [ "$CURRENT_SHA" = "0000000000000000000000000000000000000000" ]; then
        rm -f ".git/refs/heads/$BRANCH"
        echo "Fix 3: Removed bogus loose ref for $BRANCH"
    fi
fi

echo ""
echo "All repairs complete."
echo ""
git log --oneline

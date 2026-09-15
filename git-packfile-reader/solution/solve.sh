#!/bin/bash

set -e
cd /app

# Step 1: Install the packfile reader module
cp /solution/packfile_reader.py /app/packfile_reader.py

# Step 2: Patch gitlib.py to use packfile reader when loose lookup fails
python3 /solution/patch_gitlib.py

# Step 3: Install the CLI tool and make it executable
cp /solution/wyag_cat_file.py /app/wyag-cat-file
chmod +x /app/wyag-cat-file

# Verify: try reading HEAD via library
python3 -c "
import gitlib
repo = gitlib.GitRepository('/app/repo')
import subprocess
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd='/app/repo').decode().strip()
obj = gitlib.object_read(repo, head)
print(f'Library: read HEAD commit {head} (type={obj.fmt})')
"

# Verify: try reading HEAD via CLI tool
HEAD_SHA=$(cd /app/repo && git rev-parse HEAD)
echo "CLI tool type output: $(/app/wyag-cat-file -t "$HEAD_SHA" --repo /app/repo)"

echo "Packfile reading support and CLI tool installed successfully."

#!/bin/bash
set -e


mkdir -p /app
cd /app

# Initialize a deterministic git repo
git init -b master repo
cd repo
git config user.email "alice@example.com"
git config user.name "Alice"

# Commit 1: Create substantial files that encourage delta compression
for i in $(seq 1 5); do
    for j in $(seq 1 30); do
        echo "File $i, line $j: Content for delta compression testing across multiple revisions of this document."
    done > "document_$i.txt"
done

echo "[settings]" > config.ini
echo "debug = false" >> config.ini
echo "log_level = info" >> config.ini
echo "max_retries = 3" >> config.ini

git add .
GIT_AUTHOR_DATE="2024-01-01T12:00:00+00:00" GIT_COMMITTER_DATE="2024-01-01T12:00:00+00:00" \
    git commit -m "Initial commit"

# Commit 2: Modify existing files (produces similar blobs for delta encoding)
for i in $(seq 1 5); do
    echo "Updated content for revision 2 of document $i." >> "document_$i.txt"
done
git add .
GIT_AUTHOR_DATE="2024-01-02T12:00:00+00:00" GIT_COMMITTER_DATE="2024-01-02T12:00:00+00:00" \
    git commit -m "Update all documents"

# Commit 3: Add a new Python file
echo "def main():" > new_module.py
echo "    print('hello world')" >> new_module.py
echo "    return 0" >> new_module.py
echo "" >> new_module.py
echo "if __name__ == '__main__':" >> new_module.py
echo "    main()" >> new_module.py
git add .
GIT_AUTHOR_DATE="2024-01-03T12:00:00+00:00" GIT_COMMITTER_DATE="2024-01-03T12:00:00+00:00" \
    git commit -m "Add new module"

# Commit 4: Create feature branch with changes
git checkout -b feature
for i in 1 2 3; do
    echo "Feature-specific modification for document $i" >> "document_$i.txt"
done
echo "Feature documentation and notes" > feature.txt
echo "feature_flag = true" >> config.ini
git add .
GIT_AUTHOR_DATE="2024-01-04T12:00:00+00:00" GIT_COMMITTER_DATE="2024-01-04T12:00:00+00:00" \
    git commit -m "Add feature"

# Commit 5: Back to master, modify different file
git checkout master
echo "" >> new_module.py
echo "def helper():" >> new_module.py
echo "    return 42" >> new_module.py
git add .
GIT_AUTHOR_DATE="2024-01-05T12:00:00+00:00" GIT_COMMITTER_DATE="2024-01-05T12:00:00+00:00" \
    git commit -m "Add helper function"

# Commit 6: Merge (produces a merge commit with two parents)
GIT_AUTHOR_DATE="2024-01-06T12:00:00+00:00" GIT_COMMITTER_DATE="2024-01-06T12:00:00+00:00" \
    git merge feature -m "Merge branch 'feature'"

# Pack everything into a single packfile
git gc --aggressive --prune=now

# Save the HEAD tree hash before corruption (needed for loose object corruption)
HEAD_TREE=$(git rev-parse HEAD^{tree})

# Generate manifest describing expected working state (before corruption!)
python3 /tmp/generate_manifest.py

# ===== APPLY THREE DISTINCT CORRUPTIONS =====

# Corruption 1: Embed null bytes into .git/HEAD symref
# This breaks ref resolution — almost all git commands fail immediately
printf 'ref: refs/heads/master\x00\x00\x00CORRUPTED_SYMREF' > .git/HEAD

# Corruption 2: Delete the packfile index (.idx and .rev)
# Without the index, git cannot look up objects in the pack file
rm -f .git/objects/pack/*.idx .git/objects/pack/*.rev

# Corruption 3: Create a corrupt loose object that shadows a valid packed object
# Git checks loose objects before packed objects, so this will cause failures
# even after the pack index is rebuilt
mkdir -p ".git/objects/${HEAD_TREE:0:2}"
echo "corrupt_object_data" > ".git/objects/${HEAD_TREE:0:2}/${HEAD_TREE:2}"

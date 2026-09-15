#!/bin/bash
set -e

# Create a deterministic git repository
mkdir -p /app/repo && cd /app/repo
git init
git config user.name "Alice Developer"
git config user.email "alice@devteam.io"

export GIT_AUTHOR_NAME="Alice Developer"
export GIT_AUTHOR_EMAIL="alice@devteam.io"
export GIT_COMMITTER_NAME="Alice Developer"
export GIT_COMMITTER_EMAIL="alice@devteam.io"

# --- Commit 1 ---
export GIT_AUTHOR_DATE="2024-03-01T10:00:00+0000"
export GIT_COMMITTER_DATE="2024-03-01T10:00:00+0000"
echo "# Project Alpha" > README.md
cat > main.py << 'PYEOF'
#!/usr/bin/env python3

def main():
    print("Project Alpha v0.1")

if __name__ == "__main__":
    main()
PYEOF
git add .
git commit -m "Initial project setup"

# --- Commit 2 ---
export GIT_AUTHOR_DATE="2024-03-02T14:30:00+0000"
export GIT_COMMITTER_DATE="2024-03-02T14:30:00+0000"
mkdir -p src
cat > src/engine.py << 'PYEOF'
class Engine:
    def __init__(self, config):
        self.config = config
        self.running = False

    def start(self):
        self.running = True
        return self._process()

    def _process(self):
        results = []
        for key, value in self.config.items():
            results.append(f"{key}={value}")
        return results

    def stop(self):
        self.running = False
PYEOF
git add .
git commit -m "Add engine module with config processing"

# --- Commit 3 --- large file for delta compression
export GIT_AUTHOR_DATE="2024-03-03T09:15:00+0000"
export GIT_COMMITTER_DATE="2024-03-03T09:15:00+0000"
mkdir -p data
python3 -c "
for i in range(500):
    print(f'record_{i:04d}: alpha=1 beta=2 gamma=3 delta=4 epsilon=5 zeta=6 eta=7 theta=8')
" > data/records.csv
git add .
git commit -m "Add dataset with 500 records"

# --- Commit 4 --- modify large file slightly (delta compression target)
export GIT_AUTHOR_DATE="2024-03-04T16:45:00+0000"
export GIT_COMMITTER_DATE="2024-03-04T16:45:00+0000"
python3 -c "
for i in range(500):
    if i == 250:
        print(f'record_{i:04d}: MODIFIED_FIELD=999 beta=2 gamma=3 delta=4 epsilon=5 zeta=6 eta=7 theta=8')
    else:
        print(f'record_{i:04d}: alpha=1 beta=2 gamma=3 delta=4 epsilon=5 zeta=6 eta=7 theta=8')
" > data/records.csv
cat >> src/engine.py << 'PYEOF'

    def status(self):
        return {"running": self.running, "config_keys": list(self.config.keys())}
PYEOF
git add .
git commit -m "Update record 250 and add engine status method"

# --- Commit 5 ---
export GIT_AUTHOR_DATE="2024-03-05T11:00:00+0000"
export GIT_COMMITTER_DATE="2024-03-05T11:00:00+0000"
echo "v1.0.0" > VERSION
cat > CHANGELOG.md << 'MDEOF'
# Changelog

## v1.0.0
- Initial release
- Engine module with config processing
- Dataset with 500 records
MDEOF
git add .
git commit -m "Prepare v1.0.0 release"

# Annotated tag
export GIT_COMMITTER_DATE="2024-03-05T11:30:00+0000"
git tag -a v1.0.0 -m "Release version 1.0.0"

# Pack everything aggressively (moves refs into packed-refs)
git gc --aggressive --prune=now

# ========== APPLY CORRUPTIONS ==========

# Corruption 1: Poison the repository format — add unknown required extension
# This causes ALL git operations to fail immediately with:
#   "fatal: unknown repository extensions found"
git config core.repositoryformatversion 1
git config extensions.nonstandardCapability true

# Corruption 2: Delete the pack index (.idx)
rm -f /app/repo/.git/objects/pack/*.idx

# Corruption 3: Create bogus loose branch ref overriding correct packed-refs entry
BRANCH=$(sed 's|ref: refs/heads/||' < /app/repo/.git/HEAD)
mkdir -p "/app/repo/.git/refs/heads"
echo "0000000000000000000000000000000000000000" > "/app/repo/.git/refs/heads/$BRANCH"

#!/usr/bin/env python3
"""Fix the corrupted feature/string-utils branch ref by examining the merge commit."""

import subprocess
import os

REPO_DIR = '/app/repo'


def git_run(args):
    result = subprocess.run(
        ['git'] + args,
        capture_output=True, text=True, cwd=REPO_DIR
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed: {result.stderr}"
    )
    return result.stdout


# Find the merge commit on master
log_output = git_run(['log', 'master', '--format=%H %s'])

merge_sha = None
for line in log_output.strip().split('\n'):
    sha, msg = line.split(' ', 1)
    if 'Merge feature/string-utils' in msg:
        merge_sha = sha
        break

assert merge_sha is not None, "Could not find merge commit"
print(f"Found merge commit: {merge_sha}")

# Get parents of the merge commit
cat_output = git_run(['cat-file', '-p', merge_sha])
parents = []
for line in cat_output.split('\n'):
    if line.startswith('parent '):
        parents.append(line.split()[1])

assert len(parents) == 2, f"Expected 2 parents, found {len(parents)}"

# Second parent is the feature branch head
feature_sha = parents[1]
print(f"Correct feature/string-utils SHA: {feature_sha}")

# Verify it's the right commit
msg_output = git_run(['log', '--format=%s', '-1', feature_sha])
assert 'Add string utility functions' in msg_output, (
    f"Unexpected commit message for feature branch head: {msg_output}"
)

# Fix packed-refs
packed_refs_path = os.path.join(REPO_DIR, '.git/packed-refs')
with open(packed_refs_path, 'r') as f:
    lines = f.readlines()

fixed = False
with open(packed_refs_path, 'w') as f:
    for line in lines:
        if 'refs/heads/feature/string-utils' in line:
            old_sha = line.strip().split(' ', 1)[0]
            f.write(f"{feature_sha} refs/heads/feature/string-utils\n")
            print(f"Fixed ref: {old_sha} -> {feature_sha}")
            fixed = True
        else:
            f.write(line)

if not fixed:
    # If ref wasn't in packed-refs, create it as a loose ref
    ref_dir = os.path.join(REPO_DIR, '.git/refs/heads/feature')
    os.makedirs(ref_dir, exist_ok=True)
    ref_path = os.path.join(ref_dir, 'string-utils')
    with open(ref_path, 'w') as f:
        f.write(feature_sha + '\n')
    print(f"Created loose ref at {ref_path}")

print("Branch ref repair complete")

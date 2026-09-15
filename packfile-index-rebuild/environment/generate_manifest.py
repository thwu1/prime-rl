#!/usr/bin/env python3

import json
import os
import re
import subprocess

os.chdir("/app/repo")


def run(cmd):
    return subprocess.check_output(cmd, shell=True).decode().strip()


# Count objects in pack
pack_dir = "/app/repo/.git/objects/pack"
pack_files = [f for f in os.listdir(pack_dir) if f.endswith(".pack")]
pack_path = os.path.join(pack_dir, pack_files[0])
verify_output = run("git verify-pack -v " + pack_path)
object_count = len(
    [l for l in verify_output.split("\n") if re.match(r"^[0-9a-f]{40}", l)]
)

manifest = {
    "branches": sorted(
        run("git branch --format='%(refname:short)'").split("\n")
    ),
    "head_ref": "refs/heads/master",
    "total_commits": int(run("git log --oneline --all | wc -l")),
    "head_files": sorted(
        run("git ls-tree -r --name-only HEAD").split("\n")
    ),
    "file_checks": {
        "new_module.py": {"contains": ["hello world", "helper", "return 42"]},
        "feature.txt": {"contains": ["Feature"]},
        "config.ini": {"contains": ["feature_flag"]},
    },
    "head_merge_parents": 2,
    "expected_object_count": object_count,
}

with open("/app/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

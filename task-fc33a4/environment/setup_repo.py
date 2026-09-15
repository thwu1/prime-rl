#!/usr/bin/env python3
"""Create a git repository with deterministic content, record expected state,
then apply multiple forms of corruption for the recovery task."""

import subprocess
import os
import json
import shutil
import struct
import sys


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                       text=True, env=os.environ)
    if check and r.returncode != 0:
        print(f"CMD FAILED: {cmd}", file=sys.stderr)
        print(f"STDOUT: {r.stdout}", file=sys.stderr)
        print(f"STDERR: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r


def run_bytes(cmd, cwd=None):
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                          env=os.environ).stdout


REPO = "/tmp/build_repo"
DAMAGED = "/app/repo"
MANIFEST = "/app/manifest.json"

os.environ.update({
    "GIT_AUTHOR_NAME": "Alice Dev",
    "GIT_AUTHOR_EMAIL": "alice@example.com",
    "GIT_COMMITTER_NAME": "Alice Dev",
    "GIT_COMMITTER_EMAIL": "alice@example.com",
})

# ======================================================================
# PHASE 1: Create repository with deterministic content
# ======================================================================

os.makedirs(f"{REPO}/src", exist_ok=True)
os.makedirs(f"{REPO}/docs", exist_ok=True)
run("git init -b main", cwd=REPO)

# -- Commit 1: Initial structure --
os.environ["GIT_AUTHOR_DATE"] = "2024-01-15T10:00:00+00:00"
os.environ["GIT_COMMITTER_DATE"] = "2024-01-15T10:00:00+00:00"

with open(f"{REPO}/src/main.py", "w") as f:
    f.write("#!/usr/bin/env python3\n")
    f.write('"""Main application entry point."""\n\n\n')
    f.write("class Application:\n")
    f.write("    def __init__(self, config):\n")
    f.write("        self.config = config\n")
    f.write("        self.running = False\n\n")
    f.write("    def start(self):\n")
    f.write("        self.running = True\n")
    f.write("        return self.process()\n\n")
    f.write("    def process(self):\n")
    f.write("        return sum(range(1, 101))\n\n\n")
    f.write('if __name__ == "__main__":\n')
    f.write('    app = Application({"debug": True, "port": 8080})\n')
    f.write("    print(app.start())\n")

with open(f"{REPO}/src/utils.py", "w") as f:
    f.write('"""Utility functions."""\n\n\n')
    f.write("def fibonacci(n):\n")
    f.write("    if n <= 1:\n")
    f.write("        return n\n")
    f.write("    a, b = 0, 1\n")
    f.write("    for _ in range(2, n + 1):\n")
    f.write("        a, b = b, a + b\n")
    f.write("    return b\n\n\n")
    f.write("def factorial(n):\n")
    f.write("    result = 1\n")
    f.write("    for i in range(2, n + 1):\n")
    f.write("        result *= i\n")
    f.write("    return result\n")

with open(f"{REPO}/docs/README.md", "w") as f:
    f.write("# Project Alpha\n\nA sample project for testing.\n")

with open(f"{REPO}/.gitignore", "w") as f:
    f.write("__pycache__/\n*.pyc\n.env\n")

run("git add -A && git commit -m 'Initial commit: project structure'", cwd=REPO)

# -- Commit 2: Config module --
os.environ["GIT_AUTHOR_DATE"] = "2024-01-15T11:00:00+00:00"
os.environ["GIT_COMMITTER_DATE"] = "2024-01-15T11:00:00+00:00"

with open(f"{REPO}/src/config.py", "w") as f:
    f.write('"""Configuration management."""\n')
    f.write("import json\nimport os\n\n")
    f.write("DEFAULT_CONFIG = {\n")
    f.write('    "debug": False,\n')
    f.write('    "port": 8080,\n')
    f.write('    "host": "0.0.0.0",\n')
    f.write('    "log_level": "INFO"\n')
    f.write("}\n\n\n")
    f.write("def load_config(path=None):\n")
    f.write("    config = DEFAULT_CONFIG.copy()\n")
    f.write("    if path and os.path.exists(path):\n")
    f.write("        with open(path) as f:\n")
    f.write("            config.update(json.load(f))\n")
    f.write("    return config\n")

run("git add -A && git commit -m 'Add configuration module'", cwd=REPO)

# -- Feature branch: auth --
run("git checkout -b feature/auth", cwd=REPO)

os.environ["GIT_AUTHOR_DATE"] = "2024-01-15T12:00:00+00:00"
os.environ["GIT_COMMITTER_DATE"] = "2024-01-15T12:00:00+00:00"

with open(f"{REPO}/src/auth.py", "w") as f:
    f.write('"""Authentication module."""\n')
    f.write("import hashlib\nimport secrets\n\n\n")
    f.write("class AuthManager:\n")
    f.write("    def __init__(self):\n")
    f.write("        self.users = {}\n")
    f.write("        self.sessions = {}\n\n")
    f.write("    def register(self, username, password):\n")
    f.write("        salt = secrets.token_hex(16)\n")
    f.write("        hashed = hashlib.sha256((salt + password).encode()).hexdigest()\n")
    f.write('        self.users[username] = {"salt": salt, "hash": hashed}\n\n')
    f.write("    def login(self, username, password):\n")
    f.write("        if username not in self.users:\n")
    f.write("            return None\n")
    f.write("        user = self.users[username]\n")
    f.write('        hashed = hashlib.sha256((user["salt"] + password).encode()).hexdigest()\n')
    f.write('        if hashed != user["hash"]:\n')
    f.write("            return None\n")
    f.write("        token = secrets.token_hex(32)\n")
    f.write("        self.sessions[token] = username\n")
    f.write("        return token\n")

run("git add -A && git commit -m 'Add authentication module'", cwd=REPO)

# -- Commit on feature branch: integrate auth --
os.environ["GIT_AUTHOR_DATE"] = "2024-01-15T13:00:00+00:00"
os.environ["GIT_COMMITTER_DATE"] = "2024-01-15T13:00:00+00:00"

with open(f"{REPO}/src/main.py", "w") as f:
    f.write("#!/usr/bin/env python3\n")
    f.write('"""Main application with auth integration."""\n\n')
    f.write("from config import load_config\n")
    f.write("from auth import AuthManager\n\n\n")
    f.write("class Application:\n")
    f.write("    def __init__(self, config):\n")
    f.write("        self.config = config\n")
    f.write("        self.running = False\n")
    f.write("        self.auth = AuthManager()\n\n")
    f.write("    def start(self):\n")
    f.write("        self.running = True\n")
    f.write("        return self.process()\n\n")
    f.write("    def process(self):\n")
    f.write("        return sum(range(1, 101))\n\n")
    f.write("    def authenticate(self, user, pw):\n")
    f.write("        return self.auth.login(user, pw)\n\n\n")
    f.write('if __name__ == "__main__":\n')
    f.write("    config = load_config()\n")
    f.write("    app = Application(config)\n")
    f.write("    print(app.start())\n")

run("git add -A && git commit -m 'Integrate auth into main app'", cwd=REPO)

# -- Back to main --
run("git checkout main", cwd=REPO)

os.environ["GIT_AUTHOR_DATE"] = "2024-01-15T14:00:00+00:00"
os.environ["GIT_COMMITTER_DATE"] = "2024-01-15T14:00:00+00:00"

with open(f"{REPO}/src/logging_setup.py", "w") as f:
    f.write('"""Logging configuration."""\n')
    f.write("import logging\nimport sys\n\n\n")
    f.write('def setup_logging(level="INFO"):\n')
    f.write("    fmt = logging.Formatter(\n")
    f.write("        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'\n")
    f.write("    )\n")
    f.write("    handler = logging.StreamHandler(sys.stdout)\n")
    f.write("    handler.setFormatter(fmt)\n")
    f.write("    root = logging.getLogger()\n")
    f.write("    root.setLevel(getattr(logging, level))\n")
    f.write("    root.addHandler(handler)\n")
    f.write("    return root\n")

run("git add -A && git commit -m 'Add logging setup'", cwd=REPO)

# -- Tags on main --
run("git tag -a v0.1.0 -m 'Alpha release 1' HEAD~1", cwd=REPO)
run("git tag -a v0.2.0 -m 'Alpha release 2' HEAD", cwd=REPO)

# -- Pack everything --
run("git gc --aggressive --prune=now", cwd=REPO)

# -- Post-gc commit (creates loose objects not in the pack) --
os.environ["GIT_AUTHOR_DATE"] = "2024-01-15T15:00:00+00:00"
os.environ["GIT_COMMITTER_DATE"] = "2024-01-15T15:00:00+00:00"

with open(f"{REPO}/src/middleware.py", "w") as f:
    f.write('"""Request middleware."""\n\n\n')
    f.write("class RateLimiter:\n")
    f.write("    def __init__(self, max_requests=100, window=60):\n")
    f.write("        self.max_requests = max_requests\n")
    f.write("        self.window = window\n")
    f.write("        self.requests = {}\n\n")
    f.write("    def allow(self, client_id):\n")
    f.write("        import time\n")
    f.write("        now = time.time()\n")
    f.write("        if client_id not in self.requests:\n")
    f.write("            self.requests[client_id] = []\n")
    f.write("        self.requests[client_id] = [\n")
    f.write("            t for t in self.requests[client_id]\n")
    f.write("            if now - t < self.window\n")
    f.write("        ]\n")
    f.write("        if len(self.requests[client_id]) >= self.max_requests:\n")
    f.write("            return False\n")
    f.write("        self.requests[client_id].append(now)\n")
    f.write("        return True\n")

run("git add -A && git commit -m 'Add rate limiter middleware'", cwd=REPO)
run("git tag -a v0.3.0 -m 'Beta release with middleware' HEAD", cwd=REPO)

# ======================================================================
# PHASE 2: Save manifest of expected state
# ======================================================================

refs = {}
r = run("git show-ref", cwd=REPO)
for line in r.stdout.strip().splitlines():
    sha, name = line.split(" ", 1)
    refs[name] = sha

head_sha = run("git rev-parse HEAD", cwd=REPO).stdout.strip()

files_at_head = {}
r = run("git ls-tree -r HEAD", cwd=REPO)
for line in r.stdout.strip().splitlines():
    parts = line.split("\t", 1)
    path = parts[1]
    sha = parts[0].split()[2]
    content = run_bytes(f"git cat-file blob {sha}", cwd=REPO)
    files_at_head[path] = content.decode("utf-8")

log_main = []
r = run("git log --format=%H:%s main", cwd=REPO)
for line in r.stdout.strip().splitlines():
    sha, subj = line.split(":", 1)
    log_main.append({"sha": sha, "subject": subj})

log_feature = []
r = run("git log --format=%H:%s feature/auth", cwd=REPO)
for line in r.stdout.strip().splitlines():
    sha, subj = line.split(":", 1)
    log_feature.append({"sha": sha, "subject": subj})

branches_raw = run("git branch", cwd=REPO).stdout.strip().splitlines()
branches = sorted([b.strip().lstrip("* ") for b in branches_raw])

tags_raw = run("git tag", cwd=REPO).stdout.strip().splitlines()
tags = sorted([t.strip() for t in tags_raw])

manifest = {
    "head_sha": head_sha,
    "refs": refs,
    "files_at_head": files_at_head,
    "commits_main": log_main,
    "commits_feature_auth": log_feature,
    "branches": branches,
    "tags": tags,
}

os.makedirs("/app", exist_ok=True)
with open(MANIFEST, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"Manifest: {len(refs)} refs, {len(files_at_head)} files, "
      f"{len(log_main)} main commits, {len(log_feature)} feature commits, "
      f"{len(branches)} branches, {len(tags)} tags")

# ======================================================================
# PHASE 3: Create the damaged repository copy
# ======================================================================

os.makedirs(DAMAGED, exist_ok=True)
shutil.copytree(f"{REPO}/.git", f"{DAMAGED}/.git")

# -- CORRUPTION 1: Tamper with pack header (version 2 -> 3) --
pack_dir = f"{DAMAGED}/.git/objects/pack"
for fn in os.listdir(pack_dir):
    if fn.endswith(".pack"):
        pack_path = os.path.join(pack_dir, fn)
        with open(pack_path, "rb") as fh:
            data = bytearray(fh.read())
        version = struct.unpack(">I", data[4:8])[0]
        assert version == 2, f"Expected version 2, got {version}"
        data[4:8] = struct.pack(">I", 3)
        with open(pack_path, "wb") as fh:
            fh.write(data)
        print(f"CORRUPTION 1: Pack version changed to 3 in {fn}")

# -- CORRUPTION 2: Remove pack index --
for fn in os.listdir(pack_dir):
    if fn.endswith(".idx"):
        os.remove(os.path.join(pack_dir, fn))
        print(f"CORRUPTION 2: Deleted index {fn}")

# -- CORRUPTION 3: Displace loose objects to .git/salvaged/ (flat names) --
salvaged_dir = f"{DAMAGED}/.git/salvaged"
os.makedirs(salvaged_dir, exist_ok=True)
objects_dir = f"{DAMAGED}/.git/objects"
moved = 0
for d in sorted(os.listdir(objects_dir)):
    dp = os.path.join(objects_dir, d)
    if not os.path.isdir(dp) or len(d) != 2:
        continue
    if d in ("pa", "in"):
        continue
    try:
        int(d, 16)
    except ValueError:
        continue
    for fn in os.listdir(dp):
        src = os.path.join(dp, fn)
        if os.path.isfile(src):
            sha = d + fn
            shutil.move(src, os.path.join(salvaged_dir, sha))
            moved += 1
    try:
        os.rmdir(dp)
    except OSError:
        pass
print(f"CORRUPTION 3: Moved {moved} loose objects to .git/salvaged/")

# -- CORRUPTION 4: Inject dangling tag ref --
with open(f"{DAMAGED}/.git/refs/tags/unreleased-candidate", "w") as f:
    f.write("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n")
print("CORRUPTION 4: Added dangling tag ref 'unreleased-candidate'")

# -- CORRUPTION 5: Poison packed-refs with non-existent object --
packed_refs = f"{DAMAGED}/.git/packed-refs"
if os.path.exists(packed_refs):
    with open(packed_refs, "a") as f:
        f.write("cafebabecafebabecafebabecafebabecafebabe refs/remotes/origin/phantom\n")
    print("CORRUPTION 5: Added bogus packed-refs entry")

# Clean up source
shutil.rmtree(REPO)
print(f"\nDamaged repo at {DAMAGED}, manifest at {MANIFEST}")

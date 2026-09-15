#!/usr/bin/env python3
"""
Fix all configuration defects in /app/containers/.
Uses plain text replacement to preserve YAML formatting.

"""

import json
import re

CONTAINERS = "/app/containers"
SYSINFO = "/app/system_info.json"
BUNDLED_FILE = "/app/bundled_plugins.txt"

with open(BUNDLED_FILE) as f:
    bundled = set(line.strip() for line in f if line.strip())

with open(SYSINFO) as f:
    system = json.load(f)

ram_mb = system["system_memory_mb"]
max_buffers_mb = ram_mb * 25 // 100  # 1024 for 4096MB RAM


def remove_bundled_clones(text):
    """Remove git-clone lines for bundled plugins."""
    lines = text.split("\n")
    result = []
    for line in lines:
        if "git clone" in line:
            repo = line.strip().split("/")[-1].replace(".git", "")
            if repo in bundled:
                continue
        result.append(line)
    return "\n".join(result)


# ── Fix app.yml ─────────────────────────────────────────────────────

with open(f"{CONTAINERS}/app.yml") as f:
    app = f.read()

app = remove_bundled_clones(app)
app = re.sub(r'db_shared_buffers:\s*"4096MB"', f'db_shared_buffers: "{max_buffers_mb}MB"', app)
app = re.sub(r'DISCOURSE_SMTP_FORCE_TLS:\s*true', 'DISCOURSE_SMTP_FORCE_TLS: false', app)
app = re.sub(
    r'DISCOURSE_HOSTNAME:\s*"discourse\.example\.com"',
    'DISCOURSE_HOSTNAME: "forum.mysite.org"',
    app,
)
app = app.replace('"80:80"', '"8080:80"')
app = app.replace('"443:443"', '"8443:443"')
app = app.replace("\nvolumes:", '\ndocker_args: "--shm-size=512m"\n\nvolumes:', 1)

with open(f"{CONTAINERS}/app.yml", "w") as f:
    f.write(app)
print("Fixed: app.yml")

# ── Fix web.yml ─────────────────────────────────────────────────────

with open(f"{CONTAINERS}/web.yml") as f:
    web = f.read()

web = remove_bundled_clones(web)
web = re.sub(
    r'DISCOURSE_DEVELOPER_EMAILS:\s*""',
    'DISCOURSE_DEVELOPER_EMAILS: "admin@mysite.org"',
    web,
)
# Add Let's Encrypt template after SSL template
web = web.replace(
    '  - "templates/web.ssl.template.yml"',
    '  - "templates/web.ssl.template.yml"\n  - "templates/web.letsencrypt.ssl.template.yml"',
)

with open(f"{CONTAINERS}/web.yml", "w") as f:
    f.write(web)
print("Fixed: web.yml")

# ── Fix data.yml ────────────────────────────────────────────────────

with open(f"{CONTAINERS}/data.yml") as f:
    data = f.read()

data = re.sub(r'db_shared_buffers:\s*"2048MB"', f'db_shared_buffers: "{max_buffers_mb}MB"', data)
data = data.replace("\nvolumes:", '\ndocker_args: "--shm-size=512m"\n\nvolumes:', 1)

with open(f"{CONTAINERS}/data.yml", "w") as f:
    f.write(data)
print("Fixed: data.yml")

print("\nAll config defects fixed.")

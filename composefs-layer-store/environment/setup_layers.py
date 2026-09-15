#!/usr/bin/env python3
"""Create test layer directories for the content-addressed layer store task."""
import json
import os


def write_file(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(content, str):
        content = content.encode()
    with open(path, 'wb') as f:
        f.write(content)
    os.chmod(path, mode)


def create_symlink(path, target):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.symlink(target, path)


def create_dir(path, mode=0o755):
    os.makedirs(path, exist_ok=True)
    os.chmod(path, mode)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


# Deterministic binary content for deduplication testing
libfoo_data = (b"LIBFOO_CONTENT_" * 280)[:4096]
libapp_v1_data = (b"LIBAPP_V1_CONT_" * 140)[:2048]
libapp_v2_data = (b"LIBAPP_V2_CONT_" * 140)[:2048]

BASE = "/app/layers/base"
APP = "/app/layers/app"
PATCH = "/app/layers/patch"

# ===== BASE LAYER =====
create_dir(f"{BASE}/usr/bin")
create_dir(f"{BASE}/usr/lib")
create_dir(f"{BASE}/usr/share/doc")
create_dir(f"{BASE}/etc")
create_dir(f"{BASE}/etc_backup")
create_dir(f"{BASE}/var/log")

write_file(f"{BASE}/usr/bin/hello", "#!/bin/sh\necho Hello World\n", 0o755)
write_file(f"{BASE}/usr/bin/tool", "#!/bin/sh\necho Tool v1\n", 0o755)
write_file(f"{BASE}/usr/lib/libfoo.so.1", libfoo_data, 0o644)
create_symlink(f"{BASE}/usr/lib/libfoo.so", "libfoo.so.1")
write_file(f"{BASE}/usr/share/doc/README", "Base layer documentation\nVersion: 1.0\n")
write_file(f"{BASE}/etc/config.ini", "[main]\nversion=1\nname=base\n")
write_file(f"{BASE}/etc/hosts", "127.0.0.1 localhost\n::1 localhost\n")
write_file(f"{BASE}/etc_backup/config.ini.bak", "backup of config\n")
write_file(f"{BASE}/var/log/.gitkeep", "")

# ===== APP LAYER =====
create_dir(f"{APP}/usr/bin")
create_dir(f"{APP}/usr/lib")
create_dir(f"{APP}/etc")

write_file(f"{APP}/usr/bin/app", "#!/bin/sh\necho App v1\n", 0o755)
write_file(f"{APP}/usr/bin/hello", "#!/bin/sh\necho Hello from App\n", 0o755)
write_file(f"{APP}/usr/lib/libfoo.so.1", libfoo_data, 0o644)  # Same content as base
write_file(f"{APP}/usr/lib/libapp.so.1", libapp_v1_data, 0o644)
write_file(f"{APP}/etc/app.conf", "[app]\nport=8080\nworkers=4\n")

# ===== PATCH LAYER =====
create_dir(f"{PATCH}/usr/bin")
create_dir(f"{PATCH}/usr/lib")
create_dir(f"{PATCH}/etc")

write_file(f"{PATCH}/usr/bin/app", "#!/bin/sh\necho App v2 patched\n", 0o755)
write_file(f"{PATCH}/usr/lib/libapp.so.1", libapp_v2_data, 0o644)  # New version
write_file(f"{PATCH}/etc/minimal.conf", "[minimal]\nmode=production\n")

# Whiteout sidecar: declares deletions for merge
write_json(f"{PATCH}/.whiteouts.json", {
    "remove": ["usr/lib/libapp.so.1"],
    "opaque": ["etc"]
})

print("Test layers created successfully.")

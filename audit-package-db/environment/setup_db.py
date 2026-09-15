#!/usr/bin/env python3
"""Setup simulated package database with planted issues for auditing task."""
import os
import hashlib

BASE = "/opt/pkgdb"
LOCAL = os.path.join(BASE, "local")
SYNC = os.path.join(BASE, "sync")
CACHE = os.path.join(BASE, "cache")


def sha256hex(s):
    return hashlib.sha256(s.encode()).hexdigest()


def makedirs(path):
    os.makedirs(path, exist_ok=True)


def writef(path, content):
    makedirs(os.path.dirname(path))
    with open(path, "w") as f:
        f.write(content)


def pkg_content(name, version):
    return (
        f"PKGNAME={name}\n"
        f"PKGVER={version}\n"
        f"ARCH=x86_64\n"
        f"BUILDDATE=1700000000\n"
        f"PACKAGER=builder@example.org\n"
        f"SIZE=102400\n"
        f"DATA={'A' * 256}\n"
    )


def format_desc(name, version, depends=None, sha256sum=None):
    parts = []
    parts.append(f"%NAME%\n{name}\n")
    parts.append(f"%VERSION%\n{version}\n")
    if depends:
        parts.append("%DEPENDS%\n" + "\n".join(depends) + "\n")
    if sha256sum:
        parts.append(f"%SHA256SUM%\n{sha256sum}\n")
    return "\n".join(parts)


def format_files(file_list):
    return "%FILES%\n" + "\n".join(file_list) + "\n"


sync_core = [
    {"name": "libcore", "version": "2.1.0", "depends": []},
    {"name": "libcrypto", "version": "1.3.0", "depends": ["libcore>=2.0.0"]},
    {"name": "libnet", "version": "3.0.1",
     "depends": ["libcore>=2.0.0", "libcrypto>=1.2.0"]},
    {"name": "libui", "version": "4.2.0", "depends": ["libcore>=2.0.0"]},
    {"name": "libdata", "version": "1.1.0", "depends": ["libcore>=2.0.0"]},
]

sync_extra = [
    {"name": "httpd", "version": "2.4.0",
     "depends": ["libnet>=3.0.0", "libcrypto>=1.3.0"]},
    {"name": "sshd", "version": "1.9.0",
     "depends": ["libnet>=3.0.0", "libcrypto>=1.2.0"]},
    {"name": "dbengine", "version": "5.0.0",
     "depends": ["libdata>=1.1.0", "libcore>=2.1.0"]},
    {"name": "renderer", "version": "3.1.0",
     "depends": ["libui>=4.0.0", "libcore>=2.0.0"]},
    {"name": "webapp", "version": "1.0.0",
     "depends": ["httpd>=2.4.0", "dbengine>=5.0.0", "renderer>=3.0.0"]},
    {"name": "monitor", "version": "2.0.0",
     "depends": ["httpd>=2.3.0", "libnet>=3.0.0"]},
    {"name": "backup", "version": "1.5.0",
     "depends": ["libcrypto>=1.3.0", "libdata>=1.0.0"]},
    {"name": "cli-tools", "version": "0.9.0", "depends": ["libcore>=2.0.0"]},
    {"name": "plugin-a", "version": "1.0.0", "depends": ["plugin-b>=1.0.0"]},
    {"name": "plugin-b", "version": "1.0.0", "depends": ["plugin-c>=1.0.0"]},
    {"name": "plugin-c", "version": "1.0.0", "depends": ["plugin-a>=1.0.0"]},
    {"name": "libcompat", "version": "0.5.0", "depends": ["libcore>=2.0.0"]},
    {"name": "legacy-app", "version": "2.0.0",
     "depends": ["dbengine>=4.0.0", "dbengine<=4.9.9", "libdata>=1.0.0"]},
    {"name": "nettools", "version": "1.2.0", "depends": ["libpcap>=1.0.0"]},
]

# Locally installed packages — note: libnet is at 2.9.0 (partial upgrade)
local_packages = [
    {"name": "libcore", "version": "2.1.0", "depends": []},
    {"name": "libcrypto", "version": "1.3.0", "depends": ["libcore>=2.0.0"]},
    {"name": "libnet", "version": "2.9.0",
     "depends": ["libcore>=2.0.0", "libcrypto>=1.0.0"]},
    {"name": "libui", "version": "4.2.0", "depends": ["libcore>=2.0.0"]},
    {"name": "libdata", "version": "1.1.0", "depends": ["libcore>=2.0.0"]},
    {"name": "httpd", "version": "2.4.0",
     "depends": ["libnet>=3.0.0", "libcrypto>=1.3.0"]},
    {"name": "sshd", "version": "1.9.0",
     "depends": ["libnet>=3.0.0", "libcrypto>=1.2.0"]},
    {"name": "dbengine", "version": "5.0.0",
     "depends": ["libdata>=1.1.0", "libcore>=2.1.0"]},
    {"name": "renderer", "version": "3.1.0",
     "depends": ["libui>=4.0.0", "libcore>=2.0.0"]},
    {"name": "webapp", "version": "1.0.0",
     "depends": ["httpd>=2.4.0", "dbengine>=5.0.0", "renderer>=3.0.0"]},
    {"name": "monitor", "version": "2.0.0",
     "depends": ["httpd>=2.3.0", "libnet>=3.0.0"]},
    {"name": "backup", "version": "1.5.0",
     "depends": ["libcrypto>=1.3.0", "libdata>=1.0.0"]},
    {"name": "cli-tools", "version": "0.9.0", "depends": ["libcore>=2.0.0"]},
    {"name": "plugin-a", "version": "1.0.0", "depends": ["plugin-b>=1.0.0"]},
    {"name": "plugin-b", "version": "1.0.0", "depends": ["plugin-c>=1.0.0"]},
    {"name": "plugin-c", "version": "1.0.0", "depends": ["plugin-a>=1.0.0"]},
    {"name": "libcompat", "version": "0.5.0", "depends": ["libcore>=2.0.0"]},
    {"name": "legacy-app", "version": "2.0.0",
     "depends": ["dbengine>=4.0.0", "dbengine<=4.9.9", "libdata>=1.0.0"]},
    {"name": "nettools", "version": "1.2.0", "depends": ["libpcap>=1.0.0"]},
    {"name": "oldutil", "version": "0.1.0", "depends": ["libcore>=1.0.0"]},
    {"name": "legacy-driver", "version": "1.2.0", "depends": ["libcore>=2.0.0"]},
]

local_files = {
    "libcore": ["/usr/lib/libcore.so.2", "/usr/lib/libcore.so",
                "/usr/include/core.h"],
    "libcrypto": ["/usr/lib/libcrypto.so.1", "/usr/lib/libcrypto.so",
                  "/usr/lib/libssl_compat.so", "/usr/include/crypto.h"],
    "libnet": ["/usr/lib/libnet.so.2", "/usr/lib/libnet.so",
               "/usr/include/net.h"],
    "libui": ["/usr/lib/libui.so.4", "/usr/lib/libui.so",
              "/usr/include/ui.h"],
    "libdata": ["/usr/lib/libdata.so.1", "/usr/lib/libdata.so",
                "/usr/include/data.h"],
    "httpd": ["/usr/bin/httpd", "/etc/httpd/httpd.conf",
              "/usr/share/doc/httpd/README"],
    "sshd": ["/usr/bin/sshd", "/etc/sshd/sshd_config"],
    "dbengine": ["/usr/bin/dbengine", "/usr/lib/libdbengine.so",
                 "/etc/dbengine/db.conf"],
    "renderer": ["/usr/bin/renderer", "/usr/lib/librenderer.so"],
    "webapp": ["/usr/bin/webapp", "/etc/webapp/app.conf"],
    "monitor": ["/usr/bin/monitor", "/etc/monitor/monitor.conf",
                "/usr/share/doc/README"],
    "backup": ["/usr/bin/backup", "/etc/backup/backup.conf"],
    "cli-tools": ["/usr/bin/cli-info", "/usr/bin/cli-diag",
                  "/usr/share/doc/README"],
    "plugin-a": ["/usr/lib/plugins/plugin-a.so"],
    "plugin-b": ["/usr/lib/plugins/plugin-b.so"],
    "plugin-c": ["/usr/lib/plugins/plugin-c.so"],
    "libcompat": ["/usr/lib/libcompat.so", "/usr/lib/libssl_compat.so"],
    "legacy-app": ["/usr/bin/legacy-app", "/etc/legacy-app/legacy.conf"],
    "nettools": ["/usr/bin/netstat2", "/usr/bin/tracert2"],
    "oldutil": ["/usr/bin/oldutil"],
    "legacy-driver": ["/usr/lib/modules/legacy-driver.ko"],
}

cache_pkgs = {
    "libcore": {"version": "2.1.0", "corrupted": False},
    "libcrypto": {"version": "1.3.0", "corrupted": True},
    "libnet": {"version": "3.0.1", "corrupted": False},
    "libui": {"version": "4.2.0", "corrupted": False},
    "httpd": {"version": "2.4.0", "corrupted": False},
    "renderer": {"version": "3.1.0", "corrupted": True},
    "dbengine": {"version": "5.0.0", "corrupted": False},
    "cli-tools": {"version": "0.9.0", "corrupted": False},
    "backup": {"version": "1.5.0", "corrupted": False},
    "webapp": {"version": "1.0.0", "corrupted": False},
}

# Generate sync database
for repo_name, pkgs in [("core", sync_core), ("extra", sync_extra)]:
    for pkg in pkgs:
        name, version = pkg["name"], pkg["version"]
        content = pkg_content(name, version)
        expected_hash = sha256hex(content)
        desc_path = os.path.join(SYNC, repo_name, f"{name}-{version}", "desc")
        desc = format_desc(name, version, pkg.get("depends") or None,
                           expected_hash)
        writef(desc_path, desc)

# Generate local database
for pkg in local_packages:
    name, version = pkg["name"], pkg["version"]
    pkg_dir = os.path.join(LOCAL, f"{name}-{version}")
    desc = format_desc(name, version, pkg.get("depends") or None)
    writef(os.path.join(pkg_dir, "desc"), desc)
    files = format_files(local_files[name])
    writef(os.path.join(pkg_dir, "files"), files)

# Generate cache files
makedirs(CACHE)
for name, info in cache_pkgs.items():
    version = info["version"]
    content = pkg_content(name, version)
    if info["corrupted"]:
        content += "CORRUPTION=true\nTAMPERED=1\n"
    cache_path = os.path.join(CACHE, f"{name}-{version}.pkg")
    writef(cache_path, content)

# Verify critical files exist
assert os.path.isdir(LOCAL), f"ERROR: {LOCAL} not created"
assert os.path.isdir(SYNC), f"ERROR: {SYNC} not created"
assert os.path.isdir(CACHE), f"ERROR: {CACHE} not created"
local_count = len(os.listdir(LOCAL))
cache_count = len(os.listdir(CACHE))
assert local_count == 21, f"Expected 21 local packages, got {local_count}"
assert cache_count == 10, f"Expected 10 cache files, got {cache_count}"
print(f"Package database setup complete at {BASE}")
print(f"  Local packages: {local_count}")
print(f"  Cache packages: {cache_count}")

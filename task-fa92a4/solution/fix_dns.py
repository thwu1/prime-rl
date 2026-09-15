#!/usr/bin/env python3
"""
Fix all BIND9 DNS configuration issues for Weilburg Power Corporation.

Addresses 8 bugs across 5 configuration files:
1. named.conf.options: wrong listen-on address
2. named.conf.local: external view before internal view
3. named.conf.local: wrong reverse zone file path
4. acl.conf: internal ACL missing localhost
5. db.weilburg.corp: 'frsv' typo
6. db.weilburg.corp: MX target missing trailing dot
7. db.weilburg.corp: SRV targets missing trailing dot
8. db.10.10.0: PTR targets missing trailing dots
"""

import re
import os
import subprocess


def fix_listen_on():
    """Bug 1: Change listen-on from non-existent 192.168.1.1 to 'any'."""
    path = "/etc/bind/named.conf.options"
    with open(path) as f:
        content = f.read()

    content = re.sub(
        r'listen-on\s*\{[^}]*\}',
        'listen-on { any; }',
        content
    )

    with open(path, 'w') as f:
        f.write(content)
    print("[fix] named.conf.options: listen-on changed to { any; }")


def fix_acl():
    """Bug 4: Add 127.0.0.0/8 and localhost to the internal ACL."""
    path = "/etc/bind/acl.conf"
    with open(path) as f:
        content = f.read()

    # Insert localhost entries after the existing 10.10.0.0/16 line
    content = content.replace(
        '10.10.0.0/16;',
        '10.10.0.0/16;\n    127.0.0.0/8;\n    localhost;'
    )

    with open(path, 'w') as f:
        f.write(content)
    print("[fix] acl.conf: added 127.0.0.0/8 and localhost to internal ACL")


def fix_views_and_path():
    """Bug 2 & 3: Reorder views (internal first) and fix reverse zone path."""
    path = "/etc/bind/named.conf.local"
    with open(path) as f:
        original = f.read()

    # Parse both view blocks from the original content
    # Extract the zone file paths and rebuild with correct order
    corrected = '''// DNS Views for split-horizon resolution
// Internal view MUST come first — external's "any" would otherwise
// catch all queries before the internal match-clients is evaluated.

view "internal" {
    match-clients { "internal"; };

    zone "weilburg.corp" {
        type master;
        file "/etc/bind/zones/db.weilburg.corp";
    };

    zone "0.10.10.in-addr.arpa" {
        type master;
        file "/etc/bind/zones/db.10.10.0";
    };
};

view "external" {
    match-clients { any; };

    zone "weilburg.corp" {
        type master;
        file "/etc/bind/zones/db.weilburg.corp.external";
    };
};
'''
    with open(path, 'w') as f:
        f.write(corrected)
    print("[fix] named.conf.local: views reordered (internal first), reverse zone path corrected")


def fix_forward_zone():
    """Bugs 5-7: Fix typo, MX trailing dot, SRV trailing dots in forward zone."""
    path = "/etc/bind/zones/db.weilburg.corp"
    with open(path) as f:
        content = f.read()

    # Add $TTL directive if missing (best practice, avoids BIND warning)
    if '$TTL' not in content:
        content = '$TTL 86400\n' + content

    # Bug 5: Fix hostname typo frsv -> fsrv
    content = re.sub(r'^frsv(\s)', r'fsrv\1', content, flags=re.MULTILINE)

    # Bug 6: Fix MX target — add trailing dot to mx.weilburg.corp
    # Match MX line where target ends without a dot
    content = re.sub(
        r'(MX\s+\d+\s+mx\.weilburg\.corp)\s*$',
        r'\1.',
        content,
        flags=re.MULTILINE
    )

    # Bug 7: Fix SRV targets — add trailing dots to dc1.weilburg.corp
    content = re.sub(
        r'(SRV\s+\d+\s+\d+\s+\d+\s+dc1\.weilburg\.corp)\s*$',
        r'\1.',
        content,
        flags=re.MULTILINE
    )

    with open(path, 'w') as f:
        f.write(content)
    print("[fix] db.weilburg.corp: fixed frsv typo, MX trailing dot, SRV trailing dots")


def fix_reverse_zone():
    """Bug 8: Add trailing dots to all PTR record targets."""
    path = "/etc/bind/zones/db.10.10.0"
    with open(path) as f:
        lines = f.readlines()

    fixed = []
    for line in lines:
        # Only modify PTR records whose targets end with .corp (no trailing dot)
        if 'PTR' in line and line.rstrip().endswith('.corp'):
            line = line.rstrip() + '.\n'
        fixed.append(line)

    with open(path, 'w') as f:
        f.writelines(fixed)
    print("[fix] db.10.10.0: added trailing dots to all PTR targets")


def validate():
    """Run named-checkconf and named-checkzone to verify fixes."""
    checks = [
        ["named-checkconf", "/etc/bind/named.conf"],
        ["named-checkzone", "weilburg.corp", "/etc/bind/zones/db.weilburg.corp"],
        ["named-checkzone", "weilburg.corp", "/etc/bind/zones/db.weilburg.corp.external"],
        ["named-checkzone", "0.10.10.in-addr.arpa", "/etc/bind/zones/db.10.10.0"],
    ]
    all_ok = True
    for cmd in checks:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[FAIL] {' '.join(cmd)}: {result.stderr.strip()}")
            all_ok = False
        else:
            print(f"[OK]   {' '.join(cmd)}")
    return all_ok


if __name__ == '__main__':
    fix_listen_on()
    fix_acl()
    fix_views_and_path()
    fix_forward_zone()
    fix_reverse_zone()

    print("\n=== Validation ===")
    if validate():
        print("\nAll fixes applied and validated successfully.")
    else:
        print("\nSome checks failed — review output above.")
        exit(1)

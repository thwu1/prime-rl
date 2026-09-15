#!/usr/bin/env python3
"""
Secure BIND9 DNS infrastructure with DNSSEC, TSIG, RPZ, and RRL.

Implements:
1. DNSSEC inline signing with ECDSAP256SHA256 + NSEC3 (0 iterations, 0 salt)
2. TSIG-authenticated zone transfers (hmac-sha256 key "xfer-key")
3. Response Policy Zone for threat blocking
4. Response Rate Limiting
"""

import os
import base64
import secrets
import subprocess
import sys


def generate_tsig_key():
    """Generate an HMAC-SHA256 TSIG key for zone transfer authentication."""
    key_bytes = secrets.token_bytes(32)
    secret_b64 = base64.b64encode(key_bytes).decode()

    content = 'key "xfer-key" {{\n    algorithm hmac-sha256;\n    secret "{s}";\n}};\n'.format(s=secret_b64)
    with open("/etc/bind/tsig-key.conf", "w") as f:
        f.write(content)
    print("[+] TSIG key generated")
    return secret_b64


def write_dnssec_policy():
    """Write DNSSEC policy using ECDSAP256SHA256 with NSEC3 (RFC 9276).

    CRITICAL: nsec3param is a single-line statement in BIND 9.18, NOT a block.
    ARM syntax: nsec3param [ iterations int ] [ optout bool ] [ salt-length int ];
    """
    content = """\
dnssec-policy "standard" {
    keys {
        ksk key-directory lifetime unlimited algorithm ecdsap256sha256;
        zsk key-directory lifetime P30D algorithm ecdsap256sha256;
    };
    max-zone-ttl 86400;
    dnskey-ttl 300;
    nsec3param iterations 0 optout no salt-length 0;
};
"""
    with open("/etc/bind/dnssec-policy.conf", "w") as f:
        f.write(content)
    print("[+] DNSSEC policy written")


def write_rpz_zone():
    """Create Response Policy Zone file for threat blocking."""
    content = """\
$TTL 300
@   IN  SOA localhost. admin.weilburg.corp. (
            2025060101  ; serial
            3600        ; refresh
            300         ; retry
            86400       ; expire
            300         ; minimum TTL
)

@   IN  NS  localhost.

; Block malware.evil.test - NXDOMAIN
malware.evil.test       CNAME   .

; Redirect phishing.evil.test to sinkhole
phishing.evil.test      A       10.10.0.99

; Block all subdomains of botnet.evil.test - NXDOMAIN
*.botnet.evil.test      CNAME   .
"""
    with open("/etc/bind/zones/db.rpz.weilburg.corp", "w") as f:
        f.write(content)
    print("[+] RPZ zone file written")


def update_named_conf():
    """Rewrite named.conf with includes for new security config files.

    Include order: ACL first (referenced by options/views), then key/policy
    definitions, then options, then zones/views.
    """
    content = """\
// BIND9 Configuration for Weilburg Power Corporation DNS
// Security-hardened: DNSSEC, TSIG, RPZ, RRL

include "/etc/bind/acl.conf";
include "/etc/bind/tsig-key.conf";
include "/etc/bind/dnssec-policy.conf";
include "/etc/bind/named.conf.options";
include "/etc/bind/named.conf.local";
"""
    with open("/etc/bind/named.conf", "w") as f:
        f.write(content)
    print("[+] named.conf updated with security includes")


def update_options():
    """Update named.conf.options to add Response Rate Limiting."""
    content = """\
options {
    directory "/var/cache/bind";

    listen-on { any; };
    listen-on-v6 { none; };

    recursion yes;
    allow-recursion { "internal"; };
    allow-query { any; };

    dnssec-validation no;

    querylog yes;

    rate-limit {
        responses-per-second 5;
        window 5;
    };
};
"""
    with open("/etc/bind/named.conf.options", "w") as f:
        f.write(content)
    print("[+] named.conf.options updated with RRL")


def update_views():
    """Rewrite view configuration with DNSSEC, TSIG, and RPZ.

    Each zone gets its own key-directory to avoid cross-view key conflicts.
    """
    content = """\
// DNS Views for split-horizon resolution
// Security: DNSSEC inline signing, TSIG zone transfers, RPZ threat blocking

view "internal" {
    match-clients { "internal"; };

    // RPZ threat filtering (only in recursive/internal view)
    response-policy {
        zone "rpz.weilburg.corp";
    };

    zone "rpz.weilburg.corp" {
        type master;
        file "/etc/bind/zones/db.rpz.weilburg.corp";
        allow-transfer { none; };
    };

    zone "weilburg.corp" {
        type master;
        file "/etc/bind/zones/db.weilburg.corp";
        key-directory "/var/cache/bind/keys/internal";
        dnssec-policy "standard";
        inline-signing yes;
        allow-transfer { key "xfer-key"; };
    };

    zone "0.10.10.in-addr.arpa" {
        type master;
        file "/etc/bind/zones/db.10.10.0";
        key-directory "/var/cache/bind/keys/reverse";
        dnssec-policy "standard";
        inline-signing yes;
        allow-transfer { key "xfer-key"; };
    };
};

view "external" {
    match-clients { any; };

    zone "weilburg.corp" {
        type master;
        file "/etc/bind/zones/db.weilburg.corp.external";
        key-directory "/var/cache/bind/keys/external";
        dnssec-policy "standard";
        inline-signing yes;
        allow-transfer { key "xfer-key"; };
    };
};
"""
    with open("/etc/bind/named.conf.local", "w") as f:
        f.write(content)
    print("[+] Views updated with DNSSEC, TSIG, RPZ")


def setup_permissions():
    """Set file and directory permissions for DNSSEC and inline signing."""
    # Create separate key directories per view to avoid cross-view key conflicts
    for d in [
        "/var/cache/bind/keys/internal",
        "/var/cache/bind/keys/external",
        "/var/cache/bind/keys/reverse",
    ]:
        os.makedirs(d, exist_ok=True)

    # Cache + key directories must be owned by bind
    subprocess.run(["chown", "-R", "bind:bind", "/var/cache/bind"],
                   check=True)

    # Zones directory must be writable for inline-signing (.signed and .jnl files)
    subprocess.run(["chown", "bind:bind", "/etc/bind/zones"], check=True)
    subprocess.run(["chmod", "775", "/etc/bind/zones"], check=True)

    # Zone files readable by bind
    for zf in [
        "/etc/bind/zones/db.weilburg.corp",
        "/etc/bind/zones/db.weilburg.corp.external",
        "/etc/bind/zones/db.10.10.0",
        "/etc/bind/zones/db.rpz.weilburg.corp",
    ]:
        if os.path.exists(zf):
            subprocess.run(["chown", "root:bind", zf], check=True)
            subprocess.run(["chmod", "644", zf], check=True)

    # New config files readable by bind
    for cf in [
        "/etc/bind/tsig-key.conf",
        "/etc/bind/dnssec-policy.conf",
    ]:
        if os.path.exists(cf):
            subprocess.run(["chown", "root:bind", cf], check=True)
            subprocess.run(["chmod", "640", cf], check=True)

    # Ensure runtime directories exist and are writable
    os.makedirs("/run/named", exist_ok=True)
    subprocess.run(["chown", "-R", "bind:bind", "/run/named"], check=True)

    print("[+] Permissions configured")


def validate_config():
    """Run named-checkconf to verify configuration is valid."""
    result = subprocess.run(
        ["named-checkconf", "/etc/bind/named.conf"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("[FAIL] named-checkconf failed", file=sys.stderr)
        if result.stdout.strip():
            print("  stdout: " + result.stdout.strip(), file=sys.stderr)
        if result.stderr.strip():
            print("  stderr: " + result.stderr.strip(), file=sys.stderr)
        return False
    print("[+] named-checkconf: PASS")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Securing BIND9 DNS Infrastructure")
    print("=" * 60)

    print("\n[1/7] Generating TSIG key...")
    generate_tsig_key()

    print("\n[2/7] Writing DNSSEC policy...")
    write_dnssec_policy()

    print("\n[3/7] Creating RPZ zone...")
    write_rpz_zone()

    print("\n[4/7] Updating named.conf...")
    update_named_conf()

    print("\n[5/7] Updating options (RRL)...")
    update_options()

    print("\n[6/7] Updating views (DNSSEC + TSIG + RPZ)...")
    update_views()

    print("\n[7/7] Setting permissions...")
    setup_permissions()

    print("\n--- Validating configuration ---")
    if not validate_config():
        print("\nConfiguration validation failed. Aborting.", file=sys.stderr)
        sys.exit(1)

    print("\nConfiguration complete. Start named to activate.")

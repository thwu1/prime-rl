#!/usr/bin/env python3
"""Generate DNSSEC keys, sign zones, and create initial (broken) Unbound config."""
import subprocess
import os
import re

os.makedirs("/app/dns/zones", exist_ok=True)
os.chdir("/app/dns/zones")

# Generate DNSSEC keys for acme-internal.test
ksk = subprocess.check_output(
    ["ldns-keygen", "-a", "ECDSAP256SHA256", "-k", "acme-internal.test"],
    text=True
).strip()

zsk = subprocess.check_output(
    ["ldns-keygen", "-a", "ECDSAP256SHA256", "acme-internal.test"],
    text=True
).strip()

# Sign the zone with far-future expiration
subprocess.check_call([
    "ldns-signzone",
    "-o", "acme-internal.test",
    "-i", "20240101000000",
    "-e", "20350101000000",
    "acme-internal.test.zone",
    ksk, zsk
])

# BUG 4 SETUP: Extract ZSK DNSKEY record (flags 256) instead of KSK (flags 257)
# The correct trust anchor should use the KSK, not the ZSK
wrong_trust = None
with open(f"{zsk}.key") as f:
    for line in f:
        if "DNSKEY" in line:
            clean = re.sub(r";.*$", "", line).strip()
            clean = re.sub(r"\s+", " ", clean)
            wrong_trust = clean
            break

if not wrong_trust:
    raise RuntimeError(f"Could not extract DNSKEY from {zsk}.key")

# Write broken unbound.conf with multiple defects:
# BUG 2: Missing local-zone: "test." nodefault (Unbound built-in returns NXDOMAIN for .test)
# BUG 3: Missing local-zone: "113.0.203.in-addr.arpa." nodefault (built-in for RFC 5737)
# BUG 4: Trust anchor uses ZSK (flags 256) instead of KSK (flags 257)
# BUG 5: private-domain exempts evil.test from private-address filtering
config = (
    'server:\n'
    '    interface: 127.0.0.1\n'
    '    port: 5300\n'
    '    username: ""\n'
    '    chroot: ""\n'
    '    pidfile: "/app/dns/unbound.pid"\n'
    '    access-control: 127.0.0.0/8 allow\n'
    '    do-not-query-localhost: no\n'
    '    do-ip6: no\n'
    '\n'
    '    private-domain: "evil.test"\n'
    '\n'
    '    module-config: "validator iterator"\n'
    '    val-clean-additional: yes\n'
    '    harden-glue: yes\n'
    '    harden-below-nxdomain: no\n'
    '    qname-minimisation: no\n'
    '\n'
    '    private-address: 10.0.0.0/8\n'
    '    private-address: 172.16.0.0/12\n'
    '    private-address: 192.168.0.0/16\n'
    '\n'
    '    verbosity: 2\n'
    '    use-syslog: no\n'
    '    logfile: "/app/dns/unbound.log"\n'
    '    trust-anchor: "' + wrong_trust + '"\n'
    '\n'
    'stub-zone:\n'
    '    name: "acme-internal.test"\n'
    '    stub-addr: 127.0.0.1@5353\n'
    '    stub-prime: no\n'
    '\n'
    'stub-zone:\n'
    '    name: "113.0.203.in-addr.arpa"\n'
    '    stub-addr: 127.0.0.1@5353\n'
    '    stub-prime: no\n'
    '\n'
    'stub-zone:\n'
    '    name: "evil.test"\n'
    '    stub-addr: 127.0.0.1@5353\n'
    '    stub-prime: no\n'
    '\n'
    'remote-control:\n'
    '    control-enable: no\n'
)

with open("/app/dns/unbound.conf", "w") as f:
    f.write(config)

print(f"DNSSEC keys generated: KSK={ksk}, ZSK={zsk}")
print("Zone signed: acme-internal.test.zone.signed")
print("Unbound config written to /app/dns/unbound.conf")

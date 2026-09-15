#!/usr/bin/env python3
"""Diagnose and fix all DNS infrastructure configuration defects."""

import glob
import os
import re

# ============================================================
# BUG 1 FIX: NSD references unsigned zone file
# The nsd.conf uses "acme-internal.test.zone" (unsigned) instead of
# "acme-internal.test.zone.signed". This means NSD serves the zone
# without DNSKEY or RRSIG records, breaking DNSSEC entirely.
# ============================================================
nsd_conf_path = "/app/dns/nsd.conf"
with open(nsd_conf_path) as f:
    nsd_content = f.read()

nsd_content = nsd_content.replace(
    'zonefile: "acme-internal.test.zone"',
    'zonefile: "acme-internal.test.zone.signed"'
)
with open(nsd_conf_path, "w") as f:
    f.write(nsd_content)
print("FIX 1: NSD zonefile changed to signed version")

# ============================================================
# BUG 4 FIX: Find the correct KSK (flags 257) for trust anchor
# The current unbound.conf trust-anchor uses the ZSK (flags 256)
# instead of the KSK (flags 257). The KSK signs the DNSKEY RRset,
# so validation fails with the wrong key as trust anchor.
# ============================================================
os.chdir("/app/dns/zones")
ksk_trust = None
for keyfile in sorted(glob.glob("K*.key")):
    with open(keyfile) as f:
        for line in f:
            if "DNSKEY" in line and re.search(r"DNSKEY\s+257", line):
                ksk_trust = re.sub(r";.*$", "", line).strip()
                ksk_trust = re.sub(r"\s+", " ", ksk_trust)
                break
    if ksk_trust:
        break

assert ksk_trust, "Could not find KSK DNSKEY record (flags 257) in key files"
print(f"FIX 4: Found KSK trust anchor: {ksk_trust[:60]}...")

# ============================================================
# BUGS 2, 3, 4, 5: Rewrite unbound.conf with all fixes
#
# BUG 2: Missing local-zone: "test." nodefault
#   Unbound has built-in local-zone handling for the .test TLD
#   (RFC 6761) that returns NXDOMAIN by default for all .test queries.
#   This blocks stub-zone resolution entirely.
#
# BUG 3: Missing local-zone: "113.0.203.in-addr.arpa." nodefault
#   Unbound has built-in local-zone for the reverse DNS of
#   203.0.113.0/24 (RFC 5737 TEST-NET-3 documentation range).
#   PTR queries in this range get NXDOMAIN.
#
# BUG 4: Trust anchor uses ZSK (flags 256) instead of KSK (flags 257)
#   Fixed by extracting the correct KSK above.
#
# BUG 5: private-domain: "evil.test" exempts evil.test from
#   private-address filtering, allowing 10.0.0.1 through.
#   Removing it lets private-address directives filter correctly.
# ============================================================

unbound_conf = (
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
    '    local-zone: "test." nodefault\n'
    '    local-zone: "113.0.203.in-addr.arpa." nodefault\n'
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
    '    trust-anchor: "' + ksk_trust + '"\n'
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
    f.write(unbound_conf)

print("FIX 2: Added local-zone test nodefault")
print("FIX 3: Added local-zone 113.0.203.in-addr.arpa nodefault")
print("FIX 4: Trust anchor updated to KSK (flags 257)")
print("FIX 5: Removed private-domain evil.test exemption")
print("All configuration fixes applied.")

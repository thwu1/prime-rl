#!/usr/bin/env python3
"""
Fix three bugs in the OSPF SPF calculator.

Bug 1 -- /32 stub classification (inspired by holo-routing/holo#123):
    _install_stubs() incorrectly skips /32 stub networks on non-loopback
    interfaces, treating them as unnumbered p2p endpoints.  Valid host
    routes such as anycast VIPs are silently dropped.
    Fix: remove the plen==32 / is_loopback guard entirely.

Bug 2 -- network-to-router cost (RFC 2328 Section 16.1):
    _expand_network() adds back.metric when transitioning from a
    transit network vertex to an attached router.  Per the RFC the
    incremental cost for this edge is 0 -- the link cost was already
    charged on the router-to-network edge.  The current code double-counts
    it, inflating every non-directly-connected route.
    Fix: use v.cost directly (no addend).

Bug 3 -- ECMP next-hop merging:
    _offer() overwrites next_hops when an equal-cost candidate is
    found instead of computing the union.  This silently drops valid
    ECMP paths.
    Fix: merge with set union (|=).
"""


import re
import pathlib
import sys

SRC = pathlib.Path("/app/ospf_spf.py")
code = SRC.read_text()
original = code

# ---- Bug 1: remove the /32 non-loopback stub filter ----
# The if-block checking plen==32 and the following 'continue' must go.
pattern1 = r'\n[ \t]+if plen == 32 and not link\.is_loopback:\s*\n[ \t]+continue'
if not re.search(pattern1, code):
    print("ERROR: Bug 1 pattern not found in source", file=sys.stderr)
    sys.exit(1)
code = re.sub(pattern1, '', code)

# ---- Bug 2: network-to-router cost must be v.cost, not v.cost + back.metric ----
pattern2 = r'cost = v\.cost \+ back\.metric'
if not re.search(pattern2, code):
    print("ERROR: Bug 2 pattern not found in source", file=sys.stderr)
    sys.exit(1)
code = re.sub(pattern2, 'cost = v.cost', code)

# ---- Bug 3: ECMP must merge next-hop sets, not overwrite ----
pattern3 = r'c\.next_hops = nh\b'
if not re.search(pattern3, code):
    print("ERROR: Bug 3 pattern not found in source", file=sys.stderr)
    sys.exit(1)
code = re.sub(pattern3, 'c.next_hops = c.next_hops | nh', code)

if code == original:
    print("ERROR: No changes were made to the source file", file=sys.stderr)
    sys.exit(1)

SRC.write_text(code)
print("All three bugs patched.")

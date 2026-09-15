#!/usr/bin/env python3
"""
Solver for the Cilium eBPF datapath simulator.

Fixes 6 issues across 4 files:
  1. conntrack.py  - CT state decode bit shift (>>8 & 0xFF -> >>16 & 0xFFFF)
  2. identity.py   - CIDR resolution: first-match -> longest-prefix-match
  3. policy.py     - Policy evaluation: allow-before-deny -> deny-before-allow
  4. datapath.py   - Loopback detection: pkt.daddr -> pkt.saddr
  5. datapath.py   - Hairpin bypass: move before policy enforcement
  6. datapath.py   - proxy_redirect: hardcoded False -> (proxy_port > 0)
"""

import os
import sys

APP_DIR = '/app'


def fix_conntrack():
    """Fix 1: decode_ct_state uses wrong bit shift."""
    path = os.path.join(APP_DIR, 'conntrack.py')
    with open(path, 'r') as f:
        code = f.read()

    # The encoder puts rev_nat_index at bits[31:16] via << 16
    # but the decoder extracts from bits[15:8] via >> 8 & 0xFF
    # Fix: extract from bits[31:16] via >> 16 & 0xFFFF
    code = code.replace(
        '(meta >> 8) & 0xFF',
        '(meta >> 16) & 0xFFFF'
    )

    with open(path, 'w') as f:
        f.write(code)
    print("[fix] conntrack.py: decode_ct_state bit shift corrected")


def fix_identity():
    """Fix 2: CIDR resolver uses first-match instead of LPM."""
    path = os.path.join(APP_DIR, 'identity.py')
    with open(path, 'r') as f:
        code = f.read()

    # Replace the first-match loop with longest-prefix-match
    old_body = (
        "        ip = ipaddress.IPv4Address(addr)\n"
        "        for entry in self._cidr_entries:\n"
        "            if ip in entry.network:\n"
        "                return entry.identity\n"
        "        return WORLD_ID"
    )
    new_body = (
        "        ip = ipaddress.IPv4Address(addr)\n"
        "        best_match = None\n"
        "        best_prefix_len = -1\n"
        "        for entry in self._cidr_entries:\n"
        "            if ip in entry.network and entry.prefix_len > best_prefix_len:\n"
        "                best_match = entry\n"
        "                best_prefix_len = entry.prefix_len\n"
        "        return best_match.identity if best_match else WORLD_ID"
    )
    code = code.replace(old_body, new_body)

    with open(path, 'w') as f:
        f.write(code)
    print("[fix] identity.py: CIDR longest-prefix-match implemented")


def fix_policy():
    """Fix 3: Policy evaluates allow before deny, violating precedence."""
    path = os.path.join(APP_DIR, 'policy.py')
    with open(path, 'r') as f:
        code = f.read()

    old_method = '''        """Evaluate egress policy. Returns (verdict, proxy_port)."""
        # Evaluate allow rules
        allow_verdict = None
        allow_proxy = 0
        for r in self._rules:
            if r.action == "allow" and self._matches(r, src_id, dst_id, proto, dport):
                allow_verdict = Verdict.CTX_ACT_OK
                allow_proxy = r.proxy_port
                break

        if allow_verdict is not None:
            return allow_verdict, allow_proxy

        # Evaluate deny rules
        for r in self._rules:
            if r.action == "deny" and self._matches(r, src_id, dst_id, proto, dport):
                return Verdict.DROP_POLICY_DENY, 0

        return Verdict.DROP_POLICY, 0'''

    new_method = '''        """Evaluate egress policy. Returns (verdict, proxy_port)."""
        # Deny rules always take precedence
        for r in self._rules:
            if r.action == "deny" and self._matches(r, src_id, dst_id, proto, dport):
                return Verdict.DROP_POLICY_DENY, 0

        # Evaluate allow rules
        for r in self._rules:
            if r.action == "allow" and self._matches(r, src_id, dst_id, proto, dport):
                return Verdict.CTX_ACT_OK, r.proxy_port

        return Verdict.DROP_POLICY, 0'''

    code = code.replace(old_method, new_method)

    with open(path, 'w') as f:
        f.write(code)
    print("[fix] policy.py: deny-before-allow ordering corrected")


def fix_datapath():
    """Fix 4,5,6 in datapath.py."""
    path = os.path.join(APP_DIR, 'datapath.py')
    with open(path, 'r') as f:
        code = f.read()

    # Fix 4: loopback detection compares post-DNAT daddr (always equals
    # backend) instead of original saddr
    code = code.replace(
        'if pkt.daddr == backend.address:',
        'if pkt.saddr == backend.address:'
    )

    # Fix 5: hairpin bypass is dead code after the policy return.
    # Must wrap policy enforcement in `if not hairpin_flow:`
    old_policy = (
        "            # Apply network policy\n"
        "            verdict, pol_proxy = self.policy.can_egress(\n"
        "                self._seclabel, dst_id, pkt.protocol, pkt.dport)\n"
        "            if pol_proxy > 0:\n"
        "                proxy_port = pol_proxy\n"
        "\n"
        "            if verdict != Verdict.CTX_ACT_OK:\n"
        "                result.verdict = verdict\n"
        "                result.reason = \"policy_denied\"\n"
        "                return result\n"
        "\n"
        "            # Skip further checks for hairpin flows\n"
        "            if hairpin_flow:\n"
        "                pass"
    )
    new_policy = (
        "            # Hairpin flows bypass policy entirely\n"
        "            if not hairpin_flow:\n"
        "                verdict, pol_proxy = self.policy.can_egress(\n"
        "                    self._seclabel, dst_id, pkt.protocol, pkt.dport)\n"
        "                if pol_proxy > 0:\n"
        "                    proxy_port = pol_proxy\n"
        "\n"
        "                if verdict != Verdict.CTX_ACT_OK:\n"
        "                    result.verdict = verdict\n"
        "                    result.reason = \"policy_denied\"\n"
        "                    return result"
    )
    code = code.replace(old_policy, new_policy)

    # Fix 6: CT entry proxy_redirect is hardcoded False.
    # Must be derived from proxy_port.
    code = code.replace(
        'proxy_redirect=False,',
        'proxy_redirect=(proxy_port > 0),'
    )

    with open(path, 'w') as f:
        f.write(code)
    print("[fix] datapath.py: loopback, hairpin bypass, proxy_redirect corrected")


if __name__ == '__main__':
    fix_conntrack()
    fix_identity()
    fix_policy()
    fix_datapath()
    print("\nAll 6 issues fixed across 4 files.")

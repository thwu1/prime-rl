#!/usr/bin/env python3
"""
Fix three bugs in the Linux netfilter packet flow simulator.

Bug 1: NOTRACK bypass flag not propagated to conntrack.
  The notrack variable is correctly computed via _check_notrack() but
  hardcoded as False when passed to conntrack.process_packet().

Bug 2: NOTRACK treated as terminating target.
  In _process_chain(), matching a NOTRACK rule causes 'return Verdict.CONTINUE'
  which exits the function, preventing subsequent rules in the same chain from
  being evaluated. In real iptables, CT --notrack is non-terminating.

Bug 3: Conntrack entries immediately confirmed.
  New entries go directly to self.entries (confirmed) instead of self._pending.
  The confirm_pending() and rollback_pending() methods exist but are never called.
  In real Linux, conntrack entries are pending until the packet completes full
  chain traversal. Dropped packets should not leave confirmed entries.
"""

import sys


def apply_fixes():
    with open("/app/netfilter_sim.py") as f:
        code = f.read()

    original = code

    # Bug 1: Pass the actual notrack variable to conntrack.process_packet
    code = code.replace(
        "ct_ok = self.conntrack.process_packet(packet, notrack=False)",
        "ct_ok = self.conntrack.process_packet(packet, notrack=notrack)"
    )

    # Bug 2: NOTRACK is a non-terminating target - continue to next rule
    code = code.replace(
        "                elif rule.action == Action.NOTRACK:\n"
        "                    return Verdict.CONTINUE",
        "                elif rule.action == Action.NOTRACK:\n"
        "                    continue"
    )

    # Bug 3a: Create pending entries instead of immediately confirmed
    code = code.replace(
        "        # Create new conntrack entry\n"
        "        self.entries[packet.flow_key]",
        "        # Create pending conntrack entry (confirmed after chain traversal)\n"
        "        self._pending[packet.flow_key]"
    )

    # Bug 3b: Add rollback calls at each post-conntrack DROP point
    for drop_point in ["mangle_prerouting", "nat_prerouting",
                       "mangle_input", "filter_input"]:
        code = code.replace(
            '            self.dropped_packets += 1\n'
            '            return "dropped:{}"'.format(drop_point),
            '            self.conntrack.rollback_pending(packet)\n'
            '            self.dropped_packets += 1\n'
            '            return "dropped:{}"'.format(drop_point)
        )

    # Bug 3c: Add confirm call on acceptance
    code = code.replace(
        '        # 8. Local delivery - accepted\n'
        '        self.accepted_packets += 1\n'
        '        return "accepted"',
        '        # 8. Local delivery - accepted\n'
        '        self.conntrack.confirm_pending(packet)\n'
        '        self.accepted_packets += 1\n'
        '        return "accepted"'
    )

    if code == original:
        print("ERROR: No changes were applied. Source may have changed.",
              file=sys.stderr)
        sys.exit(1)

    with open("/app/netfilter_sim.py", "w") as f:
        f.write(code)

    print("Applied 3 bug fixes to /app/netfilter_sim.py:")
    print("  1. NOTRACK bypass: notrack flag now passed to conntrack")
    print("  2. NOTRACK non-terminating: continue processing after NOTRACK")
    print("  3. Conntrack confirmation: pending/confirm/rollback model")


if __name__ == "__main__":
    apply_fixes()

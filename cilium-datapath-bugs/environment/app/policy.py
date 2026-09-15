"""
Identity-based policy enforcement for the Cilium eBPF datapath simulator.

Simplified from policy_can_egress4() in bpf_lxc.c.

Policy evaluation semantics:
  - Deny rules ALWAYS take precedence over allow rules, regardless of
    the order they appear in the policy list
  - When both a deny and allow rule match the same traffic, deny wins
  - L3-only rules (protocol=0, dport=0) represent "match all L4 traffic"
    for the specified identity pair
  - When no rule matches, the default verdict is DROP_POLICY
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Tuple


class Verdict(IntEnum):
    CTX_ACT_OK = 0
    CTX_ACT_REDIRECT = 7
    DROP_INVALID = -2
    DROP_POLICY = -173
    DROP_POLICY_DENY = -174
    DROP_NO_SERVICE = -186
    DROP_UNKNOWN_CT = -153


@dataclass
class PolicyRule:
    src_identity: int = 0
    dst_identity: int = 0
    protocol: int = 0
    dport: int = 0
    action: str = "allow"
    proxy_port: int = 0


class PolicyEngine:
    """Identity-based policy enforcement engine.

    Evaluates egress policy by scanning rules for matching deny/allow
    entries. Deny rules must always take precedence over allow rules,
    regardless of the order rules appear in the policy list.
    """

    def __init__(self):
        self._rules: List[PolicyRule] = []

    def add_rule(self, rule: PolicyRule):
        self._rules.append(rule)

    def can_egress(self, src_id: int, dst_id: int,
                   proto: int, dport: int) -> Tuple[int, int]:
        """Evaluate egress policy. Returns (verdict, proxy_port)."""
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

        return Verdict.DROP_POLICY, 0

    def _matches(self, rule: PolicyRule, src_id: int, dst_id: int,
                 proto: int, dport: int) -> bool:
        if rule.src_identity and rule.src_identity != src_id:
            return False
        if rule.dst_identity and rule.dst_identity != dst_id:
            return False
        if rule.protocol and rule.protocol != proto:
            return False
        if rule.dport and rule.dport != dport:
            return False
        return True

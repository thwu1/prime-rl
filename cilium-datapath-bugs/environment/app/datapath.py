"""
Cilium eBPF Datapath Simulator - Main Processing Pipeline

Models the packet processing pipeline from Cilium's bpf_lxc.c:
  1. Per-packet LB service translation via DNAT
  2. Loopback/hairpin detection (source address vs backend address)
  3. CT state encode/decode between tail call stages
  4. Connection tracking lookup with scope selection
  5. Policy enforcement (hairpin flows bypass policy)
  6. CT entry creation with proxy redirect tracking
  7. Forwarding decision

Key semantics:
  - After LB with rev_nat_index > 0, CT scope must be SCOPE_FORWARD
    to prevent matching stale reverse entries
  - Hairpin flows (endpoint connecting to itself via service VIP) must
    bypass policy enforcement entirely
  - Loopback detection compares the packet's original source address
    against the selected backend address
  - CT entries for proxied connections must record proxy_redirect=True
    so reply traffic is correctly redirected to the L7 proxy
"""

import json
from dataclasses import dataclass
from typing import Optional

from identity import IdentityResolver, WORLD_ID
from conntrack import (
    CTMap, CTTuple, CTEntry, CTStatus, CTScope, CTDir,
    encode_ct_state, decode_ct_state,
)
from loadbalancer import LoadBalancer, LBService, LBBackend
from policy import PolicyEngine, PolicyRule, Verdict


@dataclass
class Packet:
    saddr: str
    daddr: str
    sport: int
    dport: int
    protocol: int  # 6=TCP, 17=UDP
    src_identity: int = 0


@dataclass
class PacketResult:
    verdict: int = Verdict.CTX_ACT_OK
    ct_status: int = CTStatus.CT_NEW
    proxy_port: int = 0
    reason: str = ""
    hairpin: bool = False
    loopback: bool = False
    dst_identity: int = 0


class DatapathEngine:
    """Main packet processing engine.

    Models the tail call chain from bpf_lxc.c:
      tail_handle_ipv4 -> per_packet_lb -> ct_lookup -> handle_ipv4_from_lxc
    """

    def __init__(self, lb: LoadBalancer, policy: PolicyEngine,
                 identity_resolver: IdentityResolver, local_identity: int):
        self.lb = lb
        self.policy = policy
        self.identity = identity_resolver
        self.ct_map = CTMap()
        self._seclabel = local_identity
        self._last_ct_scope: Optional[CTScope] = None

    def get_ct_entry(self, saddr, daddr, sport, dport, proto):
        """Retrieve a CT entry for inspection."""
        return self.ct_map.get_entry(saddr, daddr, sport, dport, proto)

    # ── Stage 1: Per-packet LB (service DNAT) ──

    def _do_lb(self, pkt: Packet):
        """Perform service translation via DNAT.

        Returns (packet, rev_nat_index, backend, did_lb).
        After DNAT, pkt.daddr and pkt.dport are rewritten to the backend.
        """
        svc = self.lb.lookup(pkt.daddr, pkt.dport)
        if svc is None:
            return pkt, 0, None, False
        if svc.l7_lb_proxy_port > 0:
            return pkt, 0, None, False
        be = self.lb.select_backend(svc)
        if be is None:
            return pkt, 0, None, False
        pkt.daddr = be.address
        pkt.dport = be.port
        return pkt, svc.rev_nat_index, be, True

    # ── Stage 2: Main packet processing ──

    def process_packet(self, pkt: Packet) -> PacketResult:
        """Process one packet through the full datapath pipeline.

        Implements the control flow of handle_ipv4_from_lxc() in bpf_lxc.c:
          1. Per-packet LB (DNAT service VIP -> backend)
          2. Loopback/hairpin detection (source == backend address)
          3. CT state encode/decode between stages
          4. CT lookup with scope selection
          5. Policy enforcement (hairpin bypasses policy)
          6. CT entry creation
          7. Forwarding
        """
        result = PacketResult()

        # ─── LB ───
        pkt, rev_nat_idx, backend, did_lb = self._do_lb(pkt)

        # Loopback detection: if the original source address matches the
        # selected backend, the endpoint is talking to itself through a
        # service VIP and we must flag it for SNAT.
        loopback = False
        if did_lb and backend is not None:
            if pkt.daddr == backend.address:
                loopback = True

        hairpin_flow = loopback

        # Encode LB state for next processing stage
        lb_meta = encode_ct_state(rev_nat_idx, loopback)

        # Re-resolve destination identity after DNAT
        dst_id = self.identity.resolve(pkt.daddr)
        result.dst_identity = dst_id

        # ─── CT lookup ───
        tup = CTTuple(pkt.saddr, pkt.daddr, pkt.sport, pkt.dport, pkt.protocol)

        # After LB with rev_nat_index, use SCOPE_FORWARD to prevent
        # matching stale reverse CT entries from unrelated connections.
        scope = CTScope.SCOPE_BIDIR
        restored_rev_nat, restored_loopback = decode_ct_state(lb_meta)
        if restored_rev_nat > 0:
            scope = CTScope.SCOPE_FORWARD
        self._last_ct_scope = scope

        ct_status, ct_entry = self.ct_map.lookup(tup, CTDir.CT_EGRESS, scope)
        result.ct_status = ct_status

        if ct_entry is not None:
            hairpin_flow = hairpin_flow or ct_entry.loopback
        result.hairpin = hairpin_flow
        result.loopback = loopback

        # ─── Policy enforcement ───
        proxy_port = 0

        if ct_status in (CTStatus.CT_NEW, CTStatus.CT_ESTABLISHED):
            # Apply network policy
            verdict, pol_proxy = self.policy.can_egress(
                self._seclabel, dst_id, pkt.protocol, pkt.dport)
            if pol_proxy > 0:
                proxy_port = pol_proxy

            if verdict != Verdict.CTX_ACT_OK:
                result.verdict = verdict
                result.reason = "policy_denied"
                return result

            # Skip further checks for hairpin flows
            if hairpin_flow:
                pass

        elif ct_status in (CTStatus.CT_REPLY, CTStatus.CT_RELATED):
            # Return traffic skips policy enforcement
            if ct_entry and ct_entry.proxy_redirect:
                result.reason = "proxy_reply"
        else:
            result.verdict = Verdict.DROP_UNKNOWN_CT
            result.reason = "unknown_ct"
            return result

        result.proxy_port = proxy_port

        # ─── CT entry management ───
        if ct_status == CTStatus.CT_NEW:
            new_entry = CTEntry(
                rev_nat_index=rev_nat_idx,
                loopback=loopback,
                src_sec_id=self._seclabel,
                proxy_redirect=False,
            )
            self.ct_map.create(tup, CTDir.CT_EGRESS, new_entry)

        elif ct_status == CTStatus.CT_ESTABLISHED:
            if ct_entry and ct_entry.rev_nat_index != rev_nat_idx:
                new_entry = CTEntry(
                    rev_nat_index=rev_nat_idx,
                    loopback=loopback,
                    src_sec_id=self._seclabel,
                    proxy_redirect=False,
                )
                self.ct_map.create(tup, CTDir.CT_EGRESS, new_entry)

        result.verdict = Verdict.CTX_ACT_OK
        result.reason = "forwarded"
        return result


def load_config(path: str) -> DatapathEngine:
    """Load topology, services, and policies from JSON config."""
    with open(path) as f:
        cfg = json.load(f)

    # Identity resolver
    resolver = IdentityResolver()
    for e in cfg.get("endpoints", []):
        resolver.add_endpoint(e["address"], e["identity"])
    for c in cfg.get("cidr_identities", []):
        resolver.add_cidr_identity(c["cidr"], c["prefix_len"], c["identity"])

    # Load balancer
    lb = LoadBalancer()
    for s in cfg.get("services", []):
        backends = [LBBackend(b["address"], b["port"], b.get("id", 0))
                    for b in s.get("backends", [])]
        lb.add_service(LBService(
            s["vip"], s["port"], backends,
            s.get("rev_nat_index", 0), s.get("l7_lb_proxy_port", 0)))

    # Policy engine
    pol = PolicyEngine()
    for r in cfg.get("policies", []):
        pol.add_rule(PolicyRule(
            r.get("src_identity", 0), r.get("dst_identity", 0),
            r.get("protocol", 0), r.get("dport", 0),
            r.get("action", "allow"), r.get("proxy_port", 0)))

    engine = DatapathEngine(lb, pol, resolver, cfg.get("local_identity", 0))
    return engine

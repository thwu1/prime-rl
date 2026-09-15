
"""
Tests for the Cilium eBPF datapath simulator.

Verifies connection tracking, policy enforcement, identity resolution,
hairpin flow handling, and proxy redirect semantics across the
multi-module datapath implementation.
"""

import sys
sys.path.insert(0, '/app')

import pytest
from datapath import DatapathEngine, Packet, PacketResult, load_config
from conntrack import CTStatus, CTScope
from policy import Verdict

CONFIG_PATH = '/app/config.json'


@pytest.fixture
def engine():
    """Fresh datapath engine loaded from the test configuration."""
    return load_config(CONFIG_PATH)


# -- Loopback / hairpin detection --

class TestLoopbackDetection:
    """Loopback detection must compare the original source address against
    the backend address after DNAT."""

    def test_normal_lb_not_loopback(self, engine):
        """LB to a remote backend must NOT set the loopback flag.

        10.0.0.1 -> svc 10.96.0.10:80 -> DNAT to 10.0.0.2:8080.
        Source (10.0.0.1) != backend (10.0.0.2).
        """
        pkt = Packet("10.0.0.1", "10.96.0.10", 5000, 80, 6)
        result = engine.process_packet(pkt)
        assert result.loopback is False

    def test_hairpin_lb_sets_loopback(self, engine):
        """LB where backend is the local endpoint must set loopback.

        10.0.0.1 -> svc 10.96.0.20:80 -> DNAT to 10.0.0.1:9090 (self).
        """
        pkt = Packet("10.0.0.1", "10.96.0.20", 5000, 80, 6)
        result = engine.process_packet(pkt)
        assert result.loopback is True


# -- Policy deny precedence --

class TestPolicyDenyPrecedence:
    """Deny rules must always take precedence over allow rules."""

    def test_deny_overrides_allow(self, engine):
        """Both allow and deny match 1001->1003 TCP/8443. Deny must win."""
        pkt = Packet("10.0.0.1", "10.0.0.3", 5000, 8443, 6)
        result = engine.process_packet(pkt)
        assert result.verdict == Verdict.DROP_POLICY_DENY

    def test_allow_when_no_deny(self, engine):
        """Traffic matching only an allow rule should be permitted."""
        pkt = Packet("10.0.0.1", "10.0.0.2", 5000, 8080, 6)
        result = engine.process_packet(pkt)
        assert result.verdict == Verdict.CTX_ACT_OK

    def test_default_deny(self, engine):
        """Traffic matching no rule must be denied by default."""
        pkt = Packet("10.0.0.1", "10.0.0.2", 5000, 9999, 17)
        result = engine.process_packet(pkt)
        assert result.verdict == Verdict.DROP_POLICY


# -- Hairpin policy bypass --

class TestHairpinPolicyBypass:
    """Hairpin flows (endpoint connecting to itself via service VIP)
    must bypass policy enforcement entirely."""

    def test_hairpin_bypasses_default_deny(self, engine):
        """Hairpin flow 10.0.0.1 -> svc -> 10.0.0.1 must succeed even
        though no policy rule exists for identity 1001 -> 1001."""
        pkt = Packet("10.0.0.1", "10.96.0.20", 5000, 80, 6)
        result = engine.process_packet(pkt)
        assert result.verdict == Verdict.CTX_ACT_OK


# -- Proxy redirect in CT entries --

class TestProxyRedirect:
    """CT entries must track proxy_redirect state for proxied flows."""

    def test_ct_entry_proxy_redirect(self, engine):
        """External HTTP traffic (1001->WORLD TCP/80) has proxy_port=4000.
        The CT entry must have proxy_redirect=True."""
        pkt = Packet("10.0.0.1", "1.2.3.4", 5000, 80, 6)
        result = engine.process_packet(pkt)
        assert result.verdict == Verdict.CTX_ACT_OK
        assert result.proxy_port == 4000
        ct = engine.get_ct_entry("10.0.0.1", "1.2.3.4", 5000, 80, 6)
        assert ct is not None, "CT entry was not created"
        assert ct.proxy_redirect is True


# -- CT scope selection after LB --

class TestCTScope:
    """CT scope must be SCOPE_FORWARD after LB with rev_nat_index > 0."""

    def test_scope_forward_after_lb(self, engine):
        """Service LB with rev_nat_index=1 must result in SCOPE_FORWARD."""
        pkt = Packet("10.0.0.1", "10.96.0.10", 5000, 80, 6)
        engine.process_packet(pkt)
        assert engine._last_ct_scope == CTScope.SCOPE_FORWARD

    def test_scope_bidir_without_lb(self, engine):
        """Direct traffic (no LB) should use SCOPE_BIDIR."""
        pkt = Packet("10.0.0.1", "10.0.0.2", 5000, 8080, 6)
        engine.process_packet(pkt)
        assert engine._last_ct_scope == CTScope.SCOPE_BIDIR


# -- CIDR identity resolution --

class TestCIDRIdentity:
    """CIDR identity resolution must use longest-prefix-match and
    correctly interact with policy rules."""

    def test_cidr_lpm_selects_most_specific(self, engine):
        """192.168.1.5 matches both /16 (identity 5001) and /24 (identity 5002).
        LPM must select /24 -> identity 5002."""
        pkt = Packet("10.0.0.1", "192.168.1.5", 5000, 443, 6)
        result = engine.process_packet(pkt)
        assert result.dst_identity == 5002

    def test_cidr_broader_range(self, engine):
        """192.168.2.5 only matches /16 -> identity 5001."""
        pkt = Packet("10.0.0.1", "192.168.2.5", 5000, 80, 6)
        result = engine.process_packet(pkt)
        assert result.dst_identity == 5001

    def test_l3_only_allows_any_port(self, engine):
        """L3-only allow for 1001->5002 (protocol=0, dport=0) must
        permit traffic on any port/protocol combination."""
        pkt = Packet("10.0.0.1", "192.168.1.5", 5000, 9999, 6)
        result = engine.process_packet(pkt)
        assert result.verdict == Verdict.CTX_ACT_OK

    def test_cidr_deny_separate_identity(self, engine):
        """Deny for 1001->5001 TCP/443 must not affect traffic to identity
        5002, even when the destination port is 443."""
        pkt = Packet("10.0.0.1", "192.168.1.5", 5000, 443, 6)
        result = engine.process_packet(pkt)
        assert result.verdict == Verdict.CTX_ACT_OK


# -- Integration --

class TestIntegration:
    """End-to-end scenarios exercising the full pipeline."""

    def test_service_lb_resolves_identity(self, engine):
        """After service LB, destination identity must reflect the backend."""
        pkt = Packet("10.0.0.1", "10.96.0.10", 5000, 80, 6)
        result = engine.process_packet(pkt)
        assert result.dst_identity == 1002

    def test_ct_entry_created_for_new_flow(self, engine):
        """A new flow must create a CT entry."""
        pkt = Packet("10.0.0.1", "10.0.0.2", 6000, 8080, 6)
        result = engine.process_packet(pkt)
        assert result.ct_status == CTStatus.CT_NEW
        ct = engine.get_ct_entry("10.0.0.1", "10.0.0.2", 6000, 8080, 6)
        assert ct is not None

    def test_second_packet_is_established(self, engine):
        """Second packet in same direction must match CT_ESTABLISHED."""
        pkt = Packet("10.0.0.1", "10.0.0.2", 7000, 8080, 6)
        engine.process_packet(pkt)
        result = engine.process_packet(Packet("10.0.0.1", "10.0.0.2", 7000, 8080, 6))
        assert result.ct_status == CTStatus.CT_ESTABLISHED

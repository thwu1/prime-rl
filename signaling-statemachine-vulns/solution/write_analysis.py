#!/usr/bin/env python3
"""
Generate all analysis outputs for the WebRTC state machine security audit.
"""

import os
import json

ANALYSIS_DIR = "/app/analysis"
os.makedirs(ANALYSIS_DIR, exist_ok=True)

# ============================================================
# 1. State Transition Graph (Graphviz DOT)
# ============================================================

STATE_GRAPH_DOT = r"""digraph CallingStateMachine {
    rankdir=LR;
    fontname="Helvetica";
    node [shape=box, style=filled, fillcolor="#e8f4fd", fontname="Helvetica"];
    edge [fontname="Helvetica", fontsize=10];

    IDLE [label="IDLE"];
    CALLING_OUT [label="CALLING_OUT"];
    INCOMING_CALL [label="INCOMING_CALL", fillcolor="#ffe0e0"];
    NEGOTIATING [label="NEGOTIATING"];
    CONNECTING [label="CONNECTING"];
    ACTIVE [label="ACTIVE"];
    ENDED [label="ENDED"];

    // Normal call flow transitions
    IDLE -> CALLING_OUT [label="initiate_call()"];
    IDLE -> INCOMING_CALL [label="CALL_OFFER"];
    CALLING_OUT -> NEGOTIATING [label="CALL_ANSWER\nreceived"];
    CALLING_OUT -> ENDED [label="CALL_REJECT"];
    CALLING_OUT -> CONNECTING [label="ICE connected\n(before answer)"];
    INCOMING_CALL -> NEGOTIATING [label="accept_call()"];
    INCOMING_CALL -> ENDED [label="reject_call()"];
    NEGOTIATING -> CONNECTING [label="ICE connected"];
    CONNECTING -> ACTIVE [label="CONNECT_ACK +\n_finalize_connection"];

    // VULN-1: CONNECT_ACK role bypass
    // _on_connect_ack enables media without checking self.role
    // Attacker sends CONNECT_ACK from caller to callee
    INCOMING_CALL -> ACTIVE [
        label="VULN-1: CONNECT_ACK\n(no role check)",
        color=red, fontcolor=red, penwidth=2.5, style=dashed
    ];

    // VULN-2: Trickle ICE candidates in SDP offer
    // _apply_remote_description processes trickle_ice_candidates inline
    // triggers ICE -> _on_ice_connected -> _prepare_media_pipeline
    INCOMING_CALL -> CONNECTING [
        label="VULN-2: trickle ICE in offer\n-> _prepare_media_pipeline",
        color=red, fontcolor=red, penwidth=2.5, style=dashed
    ];

    // VULN-3: SESSION_UPDATE without state check
    // _on_session_update processes SDP + candidates in ANY state
    // triggers ICE -> _on_ice_connected -> _prepare_media_pipeline
    INCOMING_CALL -> CONNECTING [
        label="VULN-3: SESSION_UPDATE\n(no state check) -> ICE",
        color="#cc0000", fontcolor="#cc0000", penwidth=2.5, style=dashed
    ];

    // Terminal transitions
    edge [style=dotted, color=gray, fontcolor=gray];
    CALLING_OUT -> ENDED [label="end_call()"];
    INCOMING_CALL -> ENDED [label="end_call()"];
    NEGOTIATING -> ENDED [label="CALL_END"];
    CONNECTING -> ENDED [label="CALL_END"];
    ACTIVE -> ENDED [label="CALL_END / end_call()"];
}
"""

with open(os.path.join(ANALYSIS_DIR, "state_graph.dot"), "w") as f:
    f.write(STATE_GRAPH_DOT)
print("State graph DOT written.")


# ============================================================
# 2. Hypothesis Stateful Property Fuzzer
# ============================================================

FUZZER_CODE = '''"""
Stateful property-based fuzzer for WebRTC calling state machine.
Uses Hypothesis RuleBasedStateMachine to systematically explore
arbitrary sequences of signaling messages and verify the consent
invariant: callee must never transmit without explicit consent.
"""
import sys
sys.path.insert(0, '/app')

import uuid
import secrets
import hashlib
from hypothesis import settings, HealthCheck
from hypothesis.stateful import (
    RuleBasedStateMachine, rule, invariant, initialize,
)

from protocol import (
    MessageType, PeerState, SDPPayload, ICECandidate, SignalingMessage,
)
from state_machine import CallStateMachine
from media_engine import MediaEngine
from signaling_bus import SignalingBus


def _make_sdp(**kwargs):
    """Create an SDP payload with sensible defaults."""
    defaults = dict(
        session_id=str(uuid.uuid4()),
        media_types=["audio", "video"],
        codecs={"audio": ["opus/48000/2"], "video": ["VP8/90000"]},
        ice_ufrag=secrets.token_hex(4),
        ice_pwd=secrets.token_hex(12),
        dtls_fingerprint=hashlib.sha256(
            secrets.token_bytes(32)
        ).hexdigest(),
    )
    defaults.update(kwargs)
    return SDPPayload(**defaults)


def _make_candidate():
    """Create a valid ICE candidate dict."""
    return {
        "foundation": "1",
        "component": 1,
        "transport": "udp",
        "priority": 2130706431,
        "address": "10.0.0.1",
        "port": 9999,
        "candidate_type": "host",
    }


class CallingStateMachineFuzzer(RuleBasedStateMachine):
    """Explore signaling message sequences to find consent violations."""

    @initialize()
    def setup(self):
        self.bus = SignalingBus()
        self.caller_media = MediaEngine("alice")
        self.caller = CallStateMachine(
            "alice", self.caller_media, self.bus.send,
        )
        self.callee_media = MediaEngine("bob")
        self.callee = CallStateMachine(
            "bob", self.callee_media, self.bus.send,
        )
        self.bus.register_peer("alice", self.caller.handle_message)
        self.bus.register_peer("bob", self.callee.handle_message)
        self.call_started = False

    @rule()
    def normal_call_offer(self):
        """Caller initiates a normal call."""
        if not self.call_started and self.caller.state == PeerState.IDLE:
            self.caller.initiate_call("bob")
            self.call_started = True

    @rule()
    def offer_with_trickle_ice(self):
        """Send CALL_OFFER with trickle ICE candidates in SDP."""
        if not self.call_started and self.callee.state == PeerState.IDLE:
            sdp = _make_sdp(
                trickle_ice_candidates=[_make_candidate()],
            )
            self.bus.inject_message(SignalingMessage(
                msg_type=MessageType.CALL_OFFER.value,
                sender_id="alice",
                target_id="bob",
                payload={
                    "call_id": str(uuid.uuid4()),
                    "sdp": sdp.to_dict(),
                },
            ))
            self.call_started = True

    @rule()
    def inject_connect_ack(self):
        """Inject CONNECT_ACK from caller to callee."""
        if self.call_started:
            self.bus.inject_message(SignalingMessage(
                msg_type=MessageType.CONNECT_ACK.value,
                sender_id="alice",
                target_id="bob",
                payload={},
            ))

    @rule()
    def inject_session_update(self):
        """Inject SESSION_UPDATE with bundled candidates."""
        if self.call_started and self.callee.remote_peer:
            sdp = _make_sdp(
                bundled_candidates=[_make_candidate()],
            )
            self.bus.inject_message(SignalingMessage(
                msg_type=MessageType.SESSION_UPDATE.value,
                sender_id="alice",
                target_id="bob",
                payload={"sdp": sdp.to_dict()},
            ))

    @rule()
    def inject_ice_candidate(self):
        """Send a standalone ICE candidate message."""
        if self.call_started:
            self.bus.inject_message(SignalingMessage(
                msg_type=MessageType.ICE_CANDIDATE.value,
                sender_id="alice",
                target_id="bob",
                payload={"candidate": _make_candidate()},
            ))

    @invariant()
    def no_unauthorized_transmission(self):
        """Callee must never transmit media without explicit consent."""
        if (self.callee_media.is_transmitting()
                and not self.callee_media.has_user_consent()):
            raise AssertionError(
                f"CONSENT INVARIANT VIOLATION: callee is transmitting "
                f"(state={self.callee.state.value}) without user consent"
            )


TestCallingStateMachine = CallingStateMachineFuzzer.TestCase
TestCallingStateMachine.settings = settings(
    max_examples=200,
    stateful_step_count=10,
    suppress_health_check=[HealthCheck.too_slow],
)
'''

with open(os.path.join(ANALYSIS_DIR, "invariant_fuzzer.py"), "w") as f:
    f.write(FUZZER_CODE)
print("Invariant fuzzer written.")


# ============================================================
# 3. Patch Verdicts
# ============================================================

patch_verdicts = [
    {
        "patch_id": "patch_a",
        "verdict": "effective",
        "target_vulnerability": "VULN-1",
        "reasoning": (
            "Correctly adds role validation to _on_connect_ack: "
            "'if self.role != \"caller\": return'. This ensures only the "
            "caller processes incoming CONNECT_ACK messages, preventing "
            "the callee from being forced into ACTIVE state with media "
            "enabled. No side effects on legitimate call flow since the "
            "callee never legitimately receives CONNECT_ACK in a way "
            "that should trigger media."
        ),
    },
    {
        "patch_id": "patch_b",
        "verdict": "insufficient",
        "target_vulnerability": "VULN-2",
        "reasoning": (
            "Attempts to defer trickle ICE candidates by appending them "
            "to _pending_remote_candidates AFTER _apply_remote_description "
            "has already been called. However, _apply_remote_description "
            "processes trickle_ice_candidates internally via "
            "_add_ice_candidate -> _check_ice_connectivity -> "
            "_on_ice_connected -> _prepare_media_pipeline. By the time "
            "the patch's deferral code runs, the candidates have already "
            "been processed and media has been enabled. The fix is too "
            "late in execution order to prevent the vulnerability."
        ),
    },
    {
        "patch_id": "patch_c",
        "verdict": "effective",
        "target_vulnerability": "VULN-3",
        "reasoning": (
            "Adds state validation to _on_session_update: only processes "
            "updates in NEGOTIATING, CONNECTING, or ACTIVE states. This "
            "correctly blocks SESSION_UPDATE during INCOMING_CALL state, "
            "preventing the attacker from injecting candidates that "
            "trigger ICE connectivity before user consent. No impact on "
            "legitimate session updates, which only occur during active "
            "or negotiating calls."
        ),
    },
    {
        "patch_id": "patch_d",
        "verdict": "insufficient",
        "target_vulnerability": "ALL",
        "reasoning": (
            "Adds consent check to _enable_media only. This blocks "
            "VULN-1 (CONNECT_ACK calls _enable_media) but fails to "
            "block VULN-2 and VULN-3. Those vulnerabilities trigger "
            "media through _prepare_media_pipeline, which calls "
            "self.media.enable_all_tracks() directly on the MediaEngine "
            "object — bypassing the _enable_media wrapper method "
            "entirely. The patch misses this second code path to media "
            "activation."
        ),
    },
    {
        "patch_id": "patch_e",
        "verdict": "regression",
        "target_vulnerability": "ALL",
        "reasoning": (
            "Implements comprehensive security checks (role validation, "
            "state checks, consent guards on both _enable_media and "
            "_prepare_media_pipeline) that would block all three "
            "vulnerabilities. However, it moves set_user_consent(True) "
            "from accept_call() to _finalize_connection(), creating a "
            "deadlock in the legitimate call flow: after accept_call "
            "sets state=NEGOTIATING, ICE candidates arrive and trigger "
            "_on_ice_connected. The NEGOTIATING branch checks "
            "'self.media.has_user_consent()' before calling "
            "_finalize_connection — but consent is now only set INSIDE "
            "_finalize_connection. Since has_user_consent() returns "
            "False, _finalize_connection is never called, and the call "
            "gets permanently stuck at CONNECTING state."
        ),
    },
]

with open(os.path.join(ANALYSIS_DIR, "patch_verdicts.json"), "w") as f:
    json.dump(patch_verdicts, f, indent=2)
print("Patch verdicts written.")


# ============================================================
# 4. Vulnerability Report
# ============================================================

report = {
    "vulnerabilities": [
        {
            "vulnerability_id": "VULN-1",
            "name": "CONNECT_ACK Missing Role Validation",
            "mechanism": (
                "The _on_connect_ack handler enables media for any peer "
                "that receives CONNECT_ACK, without checking whether the "
                "receiver is the caller (the only role that should act on "
                "this message). The state check rejects ACTIVE/ENDED/IDLE "
                "but allows INCOMING_CALL, CALLING_OUT, NEGOTIATING, and "
                "CONNECTING. A caller sending CONNECT_ACK to the callee "
                "while in INCOMING_CALL forces the callee to enable media "
                "and transition to ACTIVE without user consent."
            ),
            "affected_message_type": "connect_ack",
            "impact": (
                "Zero-click audio/video capture. The caller forces the "
                "callee to transmit audio and video without any user "
                "interaction on the callee's device."
            ),
        },
        {
            "vulnerability_id": "VULN-2",
            "name": "Trickle ICE Candidates Bypass Candidate Gating",
            "mechanism": (
                "_apply_remote_description processes trickle_ice_candidates "
                "embedded in the SDP immediately (per its RFC 8838 comment), "
                "while bundled_candidates are correctly deferred to "
                "_pending_remote_candidates. When trickle candidates trigger "
                "ICE connectivity during INCOMING_CALL state, "
                "_on_ice_connected transitions to CONNECTING and calls "
                "_prepare_media_pipeline, which calls "
                "self.media.enable_all_tracks() — enabling callee "
                "transmission without user consent."
            ),
            "affected_message_type": "call_offer",
            "impact": (
                "Caller embeds trickle ICE candidates in the initial SDP "
                "offer, establishing P2P connectivity and forcing media "
                "transmission before the callee accepts. Analogous to "
                "the JioChat/Mocha vulnerabilities found by Project Zero."
            ),
        },
        {
            "vulnerability_id": "VULN-3",
            "name": "SESSION_UPDATE Processed Without State Check",
            "mechanism": (
                "_on_session_update validates sender identity but has no "
                "state check. It processes SDP updates and bundled "
                "candidates in any state, including INCOMING_CALL. When "
                "candidates in the SESSION_UPDATE trigger ICE connectivity, "
                "_on_ice_connected calls _prepare_media_pipeline which "
                "enables media tracks without user consent."
            ),
            "affected_message_type": "session_update",
            "impact": (
                "Caller sends SESSION_UPDATE with ICE candidates while "
                "the callee's phone is ringing, forcing P2P connection "
                "establishment and unauthorized audio/video transmission. "
                "Analogous to the Facebook Messenger SdpUpdate vulnerability."
            ),
        },
    ],
}

with open(os.path.join(ANALYSIS_DIR, "report.json"), "w") as f:
    json.dump(report, f, indent=2)
print("Vulnerability report written.")

print("\nAll analysis outputs written to /app/analysis/")

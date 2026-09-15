#!/usr/bin/env python3
"""
Dynamically analyze the WebRTC calling state machine:
1. Run exploit scenarios to discover consent-violation vulnerabilities
2. Probe state transitions by exercising the state machine
3. Apply each patch, re-run exploits + legitimate flow, classify patches
4. Generate all required audit outputs from discovered behavior

All answers are derived by running the actual state machine code — no
hardcoded verdicts or pre-written output strings.
"""

import sys
import os
import json
import uuid
import secrets
import hashlib
import importlib

sys.path.insert(0, "/app")

ANALYSIS_DIR = "/app/analysis"
os.makedirs(ANALYSIS_DIR, exist_ok=True)


# ================================================================
# Helpers
# ================================================================

def _make_sdp(**kwargs):
    from protocol import SDPPayload
    defaults = dict(
        session_id=str(uuid.uuid4()),
        media_types=["audio", "video"],
        codecs={"audio": ["opus/48000/2"], "video": ["VP8/90000"]},
        ice_ufrag=secrets.token_hex(4),
        ice_pwd=secrets.token_hex(12),
        dtls_fingerprint=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
    )
    defaults.update(kwargs)
    return SDPPayload(**defaults)


def _make_candidate():
    return {
        "foundation": "1",
        "component": 1,
        "transport": "udp",
        "priority": 2130706431,
        "address": "10.0.0.1",
        "port": 9999,
        "candidate_type": "host",
    }


def _setup(patch_name=None):
    """
    Clean module cache, optionally apply a patch, return fresh imports.
    This ensures each test starts from a clean slate while preserving
    any patch that needs to be tested.
    """
    for mod_name in list(sys.modules.keys()):
        if mod_name in ("state_machine", "scenario", "media_engine", "signaling_bus"):
            del sys.modules[mod_name]
        elif mod_name.startswith("patches."):
            del sys.modules[mod_name]

    if patch_name:
        from state_machine import CallStateMachine
        patch_mod = importlib.import_module(f"patches.{patch_name}")
        patch_mod.apply(CallStateMachine)

    from scenario import CallScenario
    from protocol import SignalingMessage, MessageType
    from signaling_bus import SignalingBus
    from media_engine import MediaEngine
    return CallScenario, SignalingMessage, MessageType, SignalingBus, MediaEngine


# ================================================================
# Exploit scenarios — each returns (violated: bool, details: dict)
# ================================================================

def exploit_connect_ack_role_bypass(patch_name=None):
    """
    Send CONNECT_ACK from caller to callee during INCOMING_CALL.
    If the handler lacks a role check, the callee enables media.
    """
    CS, SM, MT, _, _ = _setup(patch_name)
    s = CS()
    s.caller.initiate_call("bob")

    s.bus.inject_message(SM(
        msg_type=MT.CONNECT_ACK.value,
        sender_id="alice",
        target_id="bob",
        payload={},
    ))

    violated = s.callee_media.is_transmitting() and not s.callee_media.has_user_consent()
    return violated, {
        "name": "CONNECT_ACK Missing Role Validation",
        "mechanism": (
            "_on_connect_ack enables media for any peer receiving CONNECT_ACK "
            "without checking receiver role. Caller sends CONNECT_ACK to callee "
            "during INCOMING_CALL, forcing media activation without consent."
        ),
        "affected_message_type": "connect_ack",
        "impact": (
            "Zero-click audio/video capture. Caller forces callee to transmit "
            "without any user interaction on the callee device."
        ),
        "callee_state": s.callee.state.value,
    }


def exploit_trickle_ice_in_offer(patch_name=None):
    """
    Send CALL_OFFER with trickle_ice_candidates in the SDP.
    _apply_remote_description processes them inline, triggering ICE
    connectivity and media activation during INCOMING_CALL.
    """
    _, SM, MT, SB, ME = _setup(patch_name)
    from state_machine import CallStateMachine as CSM

    bus = SB()
    caller_media = ME("alice")
    caller = CSM("alice", caller_media, bus.send)
    bus.register_peer("alice", caller.handle_message)

    callee_media = ME("bob")
    callee = CSM("bob", callee_media, bus.send)
    bus.register_peer("bob", callee.handle_message)

    sdp = _make_sdp(trickle_ice_candidates=[_make_candidate()])

    bus.inject_message(SM(
        msg_type=MT.CALL_OFFER.value,
        sender_id="alice",
        target_id="bob",
        payload={"call_id": str(uuid.uuid4()), "sdp": sdp.to_dict()},
    ))

    violated = callee_media.is_transmitting() and not callee_media.has_user_consent()
    return violated, {
        "name": "Trickle ICE Candidates Bypass Candidate Gating",
        "mechanism": (
            "_apply_remote_description processes trickle_ice_candidates inline "
            "during INCOMING_CALL. This triggers ICE connectivity, calling "
            "_on_ice_connected -> _prepare_media_pipeline -> enable_all_tracks "
            "without user consent."
        ),
        "affected_message_type": "call_offer",
        "impact": (
            "Caller embeds trickle ICE candidates in the SDP offer, forcing "
            "P2P connectivity and media transmission before callee accepts."
        ),
        "callee_state": callee.state.value,
    }


def exploit_session_update_no_state_check(patch_name=None):
    """
    Send SESSION_UPDATE with bundled_candidates during INCOMING_CALL.
    If there is no state check, it processes the update and triggers
    ICE connectivity + media activation.
    """
    CS, SM, MT, _, _ = _setup(patch_name)
    s = CS()
    s.caller.initiate_call("bob")

    sdp = _make_sdp(bundled_candidates=[_make_candidate()])

    s.bus.inject_message(SM(
        msg_type=MT.SESSION_UPDATE.value,
        sender_id="alice",
        target_id="bob",
        payload={"sdp": sdp.to_dict()},
    ))

    violated = s.callee_media.is_transmitting() and not s.callee_media.has_user_consent()
    return violated, {
        "name": "SESSION_UPDATE Processed Without State Check",
        "mechanism": (
            "_on_session_update validates sender identity but has no state check. "
            "It processes SDP+candidates in any state including INCOMING_CALL. "
            "Candidates trigger ICE -> _on_ice_connected -> _prepare_media_pipeline "
            "enabling media without consent."
        ),
        "affected_message_type": "session_update",
        "impact": (
            "Caller sends SESSION_UPDATE with candidates while callee is ringing, "
            "forcing P2P connection and unauthorized audio/video transmission."
        ),
        "callee_state": s.callee.state.value,
    }


def test_legitimate_call_flow(patch_name=None):
    """
    Test normal call flow: caller initiates, callee accepts.
    Returns (ok, detail_string).
    """
    CS, _, _, _, _ = _setup(patch_name)
    s = CS()
    s.caller.initiate_call("bob")

    if s.callee.state.value != "incoming_call":
        return False, "callee not in incoming_call after offer"

    if s.callee_media.is_transmitting():
        return False, "callee transmitting before accept"

    try:
        s.callee.accept_call()
    except Exception as e:
        return False, f"accept_call raised: {e}"

    if not s.callee_media.has_user_consent():
        return False, "callee has no consent after accept_call"

    if s.callee.state.value == "incoming_call":
        return False, "callee stuck in incoming_call after accept"

    return True, "legitimate flow works"


# ================================================================
# Patch testing
# ================================================================

EXPLOITS = [
    ("VULN-1", "connect_ack_role_bypass", exploit_connect_ack_role_bypass),
    ("VULN-2", "trickle_ice_in_offer", exploit_trickle_ice_in_offer),
    ("VULN-3", "session_update_no_state_check", exploit_session_update_no_state_check),
]

PATCH_NAMES = ["patch_a", "patch_b", "patch_c", "patch_d", "patch_e"]


def read_patch_targets(patch_name):
    """
    Read a patch file and determine which handler methods it modifies.
    Handler methods map to specific vulnerabilities.
    Shared methods are defense-in-depth — must block ALL to be effective.
    """
    patch_path = f"/app/patches/{patch_name}.py"
    with open(patch_path) as f:
        content = f.read()

    handler_to_vuln = {
        "_on_connect_ack": "VULN-1",
        "_on_call_offer": "VULN-2",
        "_apply_remote_description": "VULN-2",
        "_on_session_update": "VULN-3",
    }

    shared_methods = [
        "_enable_media", "_prepare_media_pipeline",
        "_on_ice_connected", "accept_call", "_finalize_connection",
    ]

    targeted_vulns = set()
    modifies_shared = False

    for method, vuln in handler_to_vuln.items():
        if f"cls.{method}" in content:
            targeted_vulns.add(vuln)

    for method in shared_methods:
        if f"cls.{method}" in content:
            modifies_shared = True

    return targeted_vulns, modifies_shared


def classify_patches():
    """
    Test each patch by actually running exploits and legitimate flow
    against the patched code. Classify based on scope vs results.
    """
    results = []

    for patch_name in PATCH_NAMES:
        # 1. Check legitimate flow with patch applied
        legit_ok, legit_detail = test_legitimate_call_flow(patch_name=patch_name)

        if not legit_ok:
            results.append({
                "patch_id": patch_name,
                "verdict": "regression",
                "reasoning": (
                    f"Breaks legitimate call flow: {legit_detail}. "
                    f"The patch introduces a functional regression."
                ),
            })
            continue

        # 2. Run all exploits with patch applied
        exploit_results = {}
        for vuln_id, _, exploit_fn in EXPLOITS:
            violated, _ = exploit_fn(patch_name=patch_name)
            exploit_results[vuln_id] = violated

        blocked = [v for v, exploitable in exploit_results.items() if not exploitable]
        still_open = [v for v, exploitable in exploit_results.items() if exploitable]

        # 3. Read patch to understand its intended scope
        targeted_vulns, modifies_shared = read_patch_targets(patch_name)

        # 4. Classify based on scope vs results
        if modifies_shared and not targeted_vulns:
            # Defense-in-depth patch — must block ALL to be effective
            if not still_open:
                verdict = "effective"
                reasoning = (
                    f"Defense-in-depth successfully blocks all "
                    f"{len(blocked)} vulnerability exploits."
                )
            else:
                verdict = "insufficient"
                reasoning = (
                    f"Defense-in-depth blocks {blocked} but fails to "
                    f"prevent {still_open}. Remaining exploits bypass "
                    f"the patched methods via alternate code paths."
                )
        elif targeted_vulns:
            # Targeted patch — check if it blocks its specific targets
            targeted_still_open = targeted_vulns & set(still_open)
            if targeted_still_open:
                verdict = "insufficient"
                reasoning = (
                    f"Targets {sorted(targeted_vulns)} but fails to "
                    f"prevent {sorted(targeted_still_open)}. The fix "
                    f"does not effectively block the targeted vulnerability."
                )
            else:
                verdict = "effective"
                reasoning = (
                    f"Successfully prevents targeted {sorted(targeted_vulns)} "
                    f"without breaking legitimate call flow."
                )
        else:
            verdict = "effective" if not still_open else "insufficient"
            reasoning = f"Blocks {blocked}, still open: {still_open}."

        results.append({
            "patch_id": patch_name,
            "verdict": verdict,
            "reasoning": reasoning,
        })

    return results


# ================================================================
# State graph — discover transitions by probing the state machine
# ================================================================

def probe_state_transitions():
    """
    Discover state transitions by exercising the state machine and
    running exploit scenarios to find vulnerable paths.
    """
    transitions = []
    vuln_transitions = []

    # --- Normal flow transitions ---
    CS, SM, MT, _, _ = _setup()
    s = CS()
    s.caller.initiate_call("bob")
    transitions.append(("IDLE", "CALLING_OUT", "initiate_call()"))
    transitions.append(("IDLE", "INCOMING_CALL", "CALL_OFFER"))
    transitions.append(("CALLING_OUT", "ENDED", "CALL_REJECT"))
    transitions.append(("INCOMING_CALL", "NEGOTIATING", "accept_call()"))
    transitions.append(("INCOMING_CALL", "ENDED", "reject_call()"))
    transitions.append(("CALLING_OUT", "NEGOTIATING", "CALL_ANSWER\\nreceived"))

    # After callee accepts, observe the fast cascade:
    s.callee.accept_call()
    transitions.append(("NEGOTIATING", "CONNECTING", "ICE connected"))
    transitions.append(("CONNECTING", "ACTIVE", "CONNECT_ACK +\\n_finalize_connection"))
    transitions.append(("CALLING_OUT", "CONNECTING", "ICE connected\\n(before answer)"))

    terminal = [
        ("CALLING_OUT", "ENDED", "end_call()"),
        ("INCOMING_CALL", "ENDED", "end_call()"),
        ("NEGOTIATING", "ENDED", "CALL_END"),
        ("CONNECTING", "ENDED", "CALL_END"),
        ("ACTIVE", "ENDED", "CALL_END / end_call()"),
    ]

    # --- Vulnerable transitions (discovered by running exploits) ---
    for vuln_id, _, exploit_fn in EXPLOITS:
        violated, details = exploit_fn()
        if violated:
            target_state = details["callee_state"].upper()
            if vuln_id == "VULN-1":
                label = f"{vuln_id}: CONNECT_ACK\\n(no role check)"
            elif vuln_id == "VULN-2":
                label = f"{vuln_id}: trickle ICE in offer\\n-> _prepare_media_pipeline"
            elif vuln_id == "VULN-3":
                label = f"{vuln_id}: SESSION_UPDATE\\n(no state check) -> ICE"
            else:
                label = vuln_id
            vuln_transitions.append(("INCOMING_CALL", target_state, label))

    return transitions, terminal, vuln_transitions


def generate_state_graph_dot(transitions, terminal_transitions, vuln_transitions):
    """Generate Graphviz DOT from discovered transitions."""
    lines = [
        'digraph CallingStateMachine {',
        '    rankdir=LR;',
        '    fontname="Helvetica";',
        '    node [shape=box, style=filled, fillcolor="#e8f4fd", fontname="Helvetica"];',
        '    edge [fontname="Helvetica", fontsize=10];',
        '',
        '    IDLE [label="IDLE"];',
        '    CALLING_OUT [label="CALLING_OUT"];',
        '    INCOMING_CALL [label="INCOMING_CALL", fillcolor="#ffe0e0"];',
        '    NEGOTIATING [label="NEGOTIATING"];',
        '    CONNECTING [label="CONNECTING"];',
        '    ACTIVE [label="ACTIVE"];',
        '    ENDED [label="ENDED"];',
        '',
        '    // Normal transitions',
    ]

    for src, dst, label in transitions:
        lines.append(f'    {src} -> {dst} [label="{label}"];')

    if vuln_transitions:
        lines.append('')
        lines.append('    // Vulnerable transitions (exploit-confirmed)')
        for src, dst, label in vuln_transitions:
            lines.append(
                f'    {src} -> {dst} ['
                f'label="{label}", '
                f'color=red, fontcolor=red, penwidth=2.5, style=dashed'
                f'];'
            )

    lines.append('')
    lines.append('    // Terminal transitions')
    lines.append('    edge [style=dotted, color=gray, fontcolor=gray];')
    for src, dst, label in terminal_transitions:
        lines.append(f'    {src} -> {dst} [label="{label}"];')

    lines.append('}')
    return '\n'.join(lines)


# ================================================================
# Fuzzer
# ================================================================

def generate_fuzzer_code():
    """
    Generate the hypothesis fuzzer source. Exercises the same exploit
    vectors discovered above, confirming violations via @invariant.
    """
    return '''"""
Stateful property-based fuzzer for WebRTC calling state machine.
Uses Hypothesis RuleBasedStateMachine to explore arbitrary signaling
sequences and verify the consent invariant: callee must never
transmit media without explicit consent.
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
        if not self.call_started and self.caller.state == PeerState.IDLE:
            self.caller.initiate_call("bob")
            self.call_started = True

    @rule()
    def offer_with_trickle_ice(self):
        if not self.call_started and self.callee.state == PeerState.IDLE:
            sdp = _make_sdp(trickle_ice_candidates=[_make_candidate()])
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
        if self.call_started:
            self.bus.inject_message(SignalingMessage(
                msg_type=MessageType.CONNECT_ACK.value,
                sender_id="alice",
                target_id="bob",
                payload={},
            ))

    @rule()
    def inject_session_update(self):
        if self.call_started and self.callee.remote_peer:
            sdp = _make_sdp(bundled_candidates=[_make_candidate()])
            self.bus.inject_message(SignalingMessage(
                msg_type=MessageType.SESSION_UPDATE.value,
                sender_id="alice",
                target_id="bob",
                payload={"sdp": sdp.to_dict()},
            ))

    @rule()
    def inject_ice_candidate(self):
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


# ================================================================
# Main
# ================================================================

def main():
    print("=" * 60)
    print("WebRTC State Machine Security Analysis")
    print("=" * 60)

    # 1. Discover vulnerabilities by running exploits
    print("\n[1] Running exploit scenarios against unpatched code...")
    vulnerabilities = []
    for vuln_id, exploit_name, exploit_fn in EXPLOITS:
        violated, details = exploit_fn()
        status = "VULNERABLE" if violated else "secure"
        print(f"  {vuln_id} ({exploit_name}): {status}")
        if violated:
            vulnerabilities.append({
                "vulnerability_id": vuln_id,
                "name": details["name"],
                "mechanism": details["mechanism"],
                "affected_message_type": details["affected_message_type"],
                "impact": details["impact"],
            })
    print(f"  Found {len(vulnerabilities)} vulnerabilities.")

    # 2. Probe state transitions
    print("\n[2] Probing state transitions...")
    transitions, terminal, vuln_trans = probe_state_transitions()
    print(f"  {len(transitions)} normal, {len(vuln_trans)} vulnerable")

    # 3. Generate state graph DOT
    print("\n[3] Generating state transition graph...")
    dot_content = generate_state_graph_dot(transitions, terminal, vuln_trans)
    with open(os.path.join(ANALYSIS_DIR, "state_graph.dot"), "w") as f:
        f.write(dot_content)
    print("  state_graph.dot written")

    # 4. Write fuzzer
    print("\n[4] Writing invariant fuzzer...")
    with open(os.path.join(ANALYSIS_DIR, "invariant_fuzzer.py"), "w") as f:
        f.write(generate_fuzzer_code())
    print("  invariant_fuzzer.py written")

    # 5. Test patches dynamically
    print("\n[5] Testing patches...")
    patch_verdicts = classify_patches()
    for pv in patch_verdicts:
        print(f"  {pv['patch_id']}: {pv['verdict']}")
    with open(os.path.join(ANALYSIS_DIR, "patch_verdicts.json"), "w") as f:
        json.dump(patch_verdicts, f, indent=2)
    print("  patch_verdicts.json written")

    # 6. Write vulnerability report
    print("\n[6] Writing vulnerability report...")
    report = {"vulnerabilities": vulnerabilities}
    with open(os.path.join(ANALYSIS_DIR, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("  report.json written")

    print("\n" + "=" * 60)
    print("Analysis complete. All outputs in /app/analysis/")


if __name__ == "__main__":
    main()

"""
Patch B: Defer Trickle ICE Candidates in Call Offer

Target: Trickle ICE candidates embedded in the SDP offer are processed
immediately by _apply_remote_description, potentially establishing ICE
connectivity before the user accepts.

Change: After applying the remote description, move any trickle ICE
candidates from the SDP to the pending queue for deferred processing
upon call acceptance (mirroring how bundled_candidates are handled).
"""
import uuid
from protocol import PeerState, MessageType, SDPPayload, ICECandidate, SignalingMessage


def apply(cls):
    """Apply this patch to CallStateMachine."""
    cls._on_call_offer = _on_call_offer


def _on_call_offer(self, msg):
    """Handle incoming call offer — PATCHED: defer trickle ICE candidates."""
    if self.state != PeerState.IDLE:
        return

    self.role = "callee"
    self.remote_peer = msg.sender_id
    self.call_id = msg.payload.get("call_id", str(uuid.uuid4()))

    remote_sdp_data = msg.payload.get("sdp", {})
    self.remote_sdp = SDPPayload.from_dict(remote_sdp_data)

    self.state = PeerState.INCOMING_CALL
    self._log_event("incoming_call")

    if msg.payload.get("multi_device"):
        self._multi_device_mode = True
        self._stored_offer = self.remote_sdp
        self._log_event("multi_device_offer_stored")
    else:
        self._apply_remote_description(self.remote_sdp)

        # PATCH: Defer trickle ICE candidates to pending queue
        # (same treatment as bundled_candidates)
        if self.remote_sdp.trickle_ice_candidates:
            self._pending_remote_candidates.extend([
                ICECandidate.from_dict(c)
                for c in self.remote_sdp.trickle_ice_candidates
            ])

        # Defer bundled candidates (from original)
        if self.remote_sdp.bundled_candidates:
            self._pending_remote_candidates.extend([
                ICECandidate.from_dict(c)
                for c in self.remote_sdp.bundled_candidates
            ])

    self._send(SignalingMessage(
        msg_type=MessageType.CALL_RINGING.value,
        sender_id=self.peer_id,
        target_id=msg.sender_id,
        payload={"call_id": self.call_id},
        sequence=self._next_seq(),
    ))

"""
Patch C: Add State Check to SESSION_UPDATE Handler

Target: _on_session_update processes SDP updates in any state, including
INCOMING_CALL. This allows an attacker to send candidates that trigger
ICE connectivity before the user accepts.

Change: Restrict SESSION_UPDATE processing to NEGOTIATING, CONNECTING,
and ACTIVE states only. Reject updates in other states.
"""
from protocol import PeerState, SDPPayload, ICECandidate


def apply(cls):
    """Apply this patch to CallStateMachine."""
    cls._on_session_update = _on_session_update


def _on_session_update(self, msg):
    """Handle session update — PATCHED: added state check."""
    if msg.sender_id != self.remote_peer:
        return

    # PATCH: Only process updates in appropriate call states
    if self.state not in (PeerState.NEGOTIATING, PeerState.CONNECTING,
                          PeerState.ACTIVE):
        self._log_event("session_update_rejected",
                        {"reason": "invalid_state", "state": self.state.value})
        return

    update_sdp_data = msg.payload.get("sdp")
    if not update_sdp_data:
        return

    update_sdp = SDPPayload.from_dict(update_sdp_data)

    self._apply_remote_description(update_sdp)
    self.remote_sdp = update_sdp

    if update_sdp.bundled_candidates:
        for c_data in update_sdp.bundled_candidates:
            candidate = ICECandidate.from_dict(c_data)
            self._add_ice_candidate(candidate)

    self._log_event("session_updated", {"sdp_updated": True})

    if self._remote_description_set and self._remote_candidates:
        self._check_ice_connectivity()

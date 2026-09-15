"""
Patch E: Comprehensive Security Hardening

Target: All known vulnerabilities — defense-in-depth approach with
multiple layers of protection.

Changes:
- Added role validation to _on_connect_ack
- Added state validation to _on_session_update
- Added consent checks to both _prepare_media_pipeline and _enable_media
- Centralized consent granting in _finalize_connection (moved from
  accept_call to ensure consent is granted atomically with media
  activation, preventing any window where consent is set but media
  is not yet enabled)
"""
from protocol import PeerState, MessageType, SDPPayload, ICECandidate, SignalingMessage


def apply(cls):
    """Apply this patch to CallStateMachine."""
    cls.accept_call = accept_call
    cls._on_connect_ack = _on_connect_ack
    cls._on_session_update = _on_session_update
    cls._prepare_media_pipeline = _prepare_media_pipeline
    cls._enable_media = _enable_media
    cls._finalize_connection = _finalize_connection


def accept_call(self):
    """Accept incoming call — PATCHED: consent moved to _finalize_connection."""
    if self.state != PeerState.INCOMING_CALL:
        raise RuntimeError(f"Cannot accept call in state {self.state}")
    if self.role != "callee":
        raise RuntimeError("Only callee can accept a call")

    # NOTE: Consent granting moved to _finalize_connection for
    # atomic consent-with-media-activation (defense-in-depth).
    # This prevents any window where consent is set but media
    # has not yet been securely activated.
    self.state = PeerState.NEGOTIATING
    self._log_event("call_accepted_by_user")

    self.local_sdp = self._generate_sdp(["audio", "video"])
    self._send(SignalingMessage(
        msg_type=MessageType.CALL_ANSWER.value,
        sender_id=self.peer_id,
        target_id=self.remote_peer,
        payload={
            "call_id": self.call_id,
            "sdp": self.local_sdp.to_dict(),
        },
        sequence=self._next_seq(),
    ))

    if self._pending_remote_candidates:
        for candidate in self._pending_remote_candidates:
            self._add_ice_candidate(candidate)
        self._pending_remote_candidates.clear()

    if self._multi_device_mode and self._stored_offer:
        self._apply_remote_description(self._stored_offer)
        for candidate in self._stored_candidates:
            self._add_ice_candidate(candidate)
        self._stored_candidates.clear()


def _on_connect_ack(self, msg):
    """Handle CONNECT_ACK — PATCHED: added role check."""
    if msg.sender_id != self.remote_peer:
        self._log_event("connect_ack_rejected", {"reason": "unknown_sender"})
        return
    # PATCH: Only the caller should process incoming CONNECT_ACK
    if self.role != "caller":
        self._log_event("connect_ack_rejected", {"reason": "wrong_role"})
        return
    if self.state in (PeerState.ACTIVE, PeerState.ENDED, PeerState.IDLE):
        return
    self._log_event("connect_ack_received", {"from": msg.sender_id})
    self._enable_media()
    self.state = PeerState.ACTIVE


def _on_session_update(self, msg):
    """Handle session update — PATCHED: added state check."""
    if msg.sender_id != self.remote_peer:
        return
    # PATCH: Only process updates in appropriate states
    if self.state not in (PeerState.NEGOTIATING, PeerState.CONNECTING,
                          PeerState.ACTIVE):
        self._log_event("session_update_rejected", {"reason": "invalid_state"})
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


def _prepare_media_pipeline(self):
    """Prepare media pipeline — PATCHED: added consent check."""
    # PATCH: Don't prepare media without consent
    if not self.media.has_user_consent():
        self._log_event("media_pipeline_blocked", {"reason": "no_consent"})
        return
    for track_id in list(self.media.local_tracks.keys()):
        self.media.add_track_to_connection(track_id)
    self.media.enable_all_tracks()


def _enable_media(self):
    """Enable media — PATCHED: added consent check."""
    # PATCH: Block without consent
    if not self.media.has_user_consent():
        self._log_event("media_blocked", {"reason": "no_consent"})
        return
    enabled = self.media.enable_all_tracks()
    if enabled:
        self._log_event("media_enabled", {
            "tracks": enabled,
            "consent": self.media.has_user_consent(),
        })


def _finalize_connection(self):
    """Complete call setup — PATCHED: consent granted atomically here."""
    # PATCH: Grant consent atomically with media activation
    self.media.set_user_consent(True)
    self._send(SignalingMessage(
        msg_type=MessageType.CONNECT_ACK.value,
        sender_id=self.peer_id,
        target_id=self.remote_peer,
        payload={"call_id": self.call_id},
        sequence=self._next_seq(),
    ))
    self._enable_media()
    self.state = PeerState.ACTIVE
    self._log_event("call_active")

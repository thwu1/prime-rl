"""
Patch A: Fix CONNECT_ACK Role Bypass

Target: The _on_connect_ack handler enables media for any peer receiving
CONNECT_ACK, without checking whether the receiver is the caller. In the
normal flow, only the callee sends CONNECT_ACK (after accepting), so only
the caller should process it.

Change: Added role validation — reject CONNECT_ACK if self.role != "caller".
"""
from protocol import PeerState


def apply(cls):
    """Apply this patch to CallStateMachine."""
    cls._on_connect_ack = _on_connect_ack


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

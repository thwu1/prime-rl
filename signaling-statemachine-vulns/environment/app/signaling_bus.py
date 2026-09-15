"""
Signaling Message Bus

Routes signaling messages between registered peers, simulating
the signaling server in a WebRTC call setup. Supports message
injection for testing exploit scenarios.
"""

from typing import Dict, Callable, List
from protocol import SignalingMessage


class SignalingBus:
    """Routes signaling messages between registered peer handlers."""

    def __init__(self):
        self._peers: Dict[str, Callable[[SignalingMessage], None]] = {}
        self._message_log: List[SignalingMessage] = []

    def register_peer(self, peer_id: str,
                      handler: Callable[[SignalingMessage], None]):
        self._peers[peer_id] = handler

    def unregister_peer(self, peer_id: str):
        self._peers.pop(peer_id, None)

    def send(self, msg: SignalingMessage):
        """Route a message to its target peer."""
        self._message_log.append(msg)
        target = msg.target_id
        if target and target in self._peers:
            self._peers[target](msg)

    def inject_message(self, msg: SignalingMessage):
        """Inject a crafted message directly into the bus.
        Simulates an attacker sending arbitrary signaling messages."""
        self._message_log.append(msg)
        target = msg.target_id
        if target and target in self._peers:
            self._peers[target](msg)

    def get_message_log(self):
        return list(self._message_log)

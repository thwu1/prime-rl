"""
Call Scenario Helper

Provides convenient setup for testing call flows between
a caller and callee using the signaling framework.
"""

from protocol import SignalingMessage
from state_machine import CallStateMachine
from media_engine import MediaEngine
from signaling_bus import SignalingBus


class CallScenario:
    """Sets up a caller and callee connected via a signaling bus."""

    def __init__(self, caller_id: str = "alice", callee_id: str = "bob"):
        self.bus = SignalingBus()

        self.caller_media = MediaEngine(caller_id)
        self.caller = CallStateMachine(
            peer_id=caller_id,
            media_engine=self.caller_media,
            send_fn=self.bus.send,
        )

        self.callee_media = MediaEngine(callee_id)
        self.callee = CallStateMachine(
            peer_id=callee_id,
            media_engine=self.callee_media,
            send_fn=self.bus.send,
        )

        self.bus.register_peer(caller_id, self.caller.handle_message)
        self.bus.register_peer(callee_id, self.callee.handle_message)

    def get_callee_status(self):
        """Get a summary of the callee's transmission and consent state."""
        return {
            "state": self.callee.state.value,
            "transmitting": self.callee_media.is_transmitting(),
            "consent": self.callee_media.has_user_consent(),
            "unauthorized": bool(
                self.callee_media.get_unauthorized_transmissions()
            ),
            "tracks": [
                {
                    "id": t.track_id,
                    "kind": t.kind.value,
                    "state": t.state.value,
                }
                for t in self.callee_media.get_transmitting_tracks()
            ],
        }

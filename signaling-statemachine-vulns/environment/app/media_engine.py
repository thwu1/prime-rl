"""
Simulated Media Engine for WebRTC Calling

Manages audio and video tracks, simulating the media capture and
transmission subsystem. Tracks must be explicitly added to a peer
connection and enabled before media is transmitted.
"""

from dataclasses import dataclass
from typing import List, Dict
from enum import Enum


class TrackKind(Enum):
    AUDIO = "audio"
    VIDEO = "video"


class TrackState(Enum):
    CREATED = "created"
    ADDED = "added"
    ENABLED = "enabled"
    DISABLED = "disabled"
    REMOVED = "removed"


@dataclass
class MediaTrack:
    track_id: str
    kind: TrackKind
    state: TrackState = TrackState.CREATED
    label: str = ""

    def enable(self):
        if self.state in (TrackState.ADDED, TrackState.DISABLED):
            self.state = TrackState.ENABLED
            return True
        return False

    def disable(self):
        if self.state == TrackState.ENABLED:
            self.state = TrackState.DISABLED
            return True
        return False


class MediaEngine:
    """Simulates local media capture devices and transmission state."""

    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.local_tracks: Dict[str, MediaTrack] = {}
        self._transmission_log: List[Dict] = []
        self._user_consent_given = False
        self._init_local_devices()

    def _init_local_devices(self):
        self.local_tracks["mic_0"] = MediaTrack(
            track_id="mic_0",
            kind=TrackKind.AUDIO,
            state=TrackState.CREATED,
            label="Default Microphone",
        )
        self.local_tracks["cam_0"] = MediaTrack(
            track_id="cam_0",
            kind=TrackKind.VIDEO,
            state=TrackState.CREATED,
            label="Default Camera",
        )

    def add_track_to_connection(self, track_id: str):
        """Add a local track to the peer connection."""
        if track_id in self.local_tracks:
            track = self.local_tracks[track_id]
            if track.state == TrackState.CREATED:
                track.state = TrackState.ADDED
                self._log("track_added", track_id, track.kind.value)
                return True
        return False

    def enable_all_tracks(self):
        """Enable all local tracks for active transmission."""
        enabled = []
        for track_id, track in self.local_tracks.items():
            if track.state in (TrackState.CREATED, TrackState.ADDED,
                               TrackState.DISABLED):
                if track.state == TrackState.CREATED:
                    track.state = TrackState.ADDED
                track.state = TrackState.ENABLED
                self._log("track_enabled", track_id, track.kind.value)
                enabled.append(track_id)
        return enabled

    def disable_all_tracks(self):
        for track_id, track in self.local_tracks.items():
            if track.state == TrackState.ENABLED:
                track.disable()
                self._log("track_disabled", track_id, track.kind.value)

    def is_transmitting(self):
        """Check if any local track is actively transmitting."""
        return any(
            t.state == TrackState.ENABLED for t in self.local_tracks.values()
        )

    def get_transmitting_tracks(self):
        return [
            t for t in self.local_tracks.values()
            if t.state == TrackState.ENABLED
        ]

    def set_user_consent(self, consent: bool):
        self._user_consent_given = consent

    def has_user_consent(self):
        return self._user_consent_given

    def get_unauthorized_transmissions(self):
        """Return log entries where tracks were enabled without consent."""
        return [
            e for e in self._transmission_log
            if e["event"] == "track_enabled" and not e["consent"]
        ]

    def get_transmission_log(self):
        return list(self._transmission_log)

    def _log(self, event_type, track_id, track_kind):
        self._transmission_log.append({
            "event": event_type,
            "track_id": track_id,
            "kind": track_kind,
            "consent": self._user_consent_given,
        })

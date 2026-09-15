"""
WebRTC Signaling Protocol Definitions

Defines message types, peer states, and data structures for the
WebRTC calling signaling protocol. Based on standard WebRTC
offer/answer model with ICE candidate exchange.
"""

import json
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


class MessageType(Enum):
    """Signaling message types for call setup and management."""
    # Call lifecycle
    CALL_OFFER = "call_offer"
    CALL_RINGING = "call_ringing"
    CALL_ANSWER = "call_answer"
    CALL_REJECT = "call_reject"
    CALL_END = "call_end"

    # ICE candidates (trickle ICE)
    ICE_CANDIDATE = "ice_candidate"

    # Connection handshake
    CONNECT_ACK = "connect_ack"

    # Mid-call renegotiation
    SESSION_UPDATE = "session_update"

    # Diagnostics
    PEER_STATE_QUERY = "peer_state_query"
    PEER_STATE_REPORT = "peer_state_report"


class PeerState(Enum):
    """States in the calling state machine."""
    IDLE = "idle"
    CALLING_OUT = "calling_out"
    INCOMING_CALL = "incoming_call"
    NEGOTIATING = "negotiating"
    CONNECTING = "connecting"
    ACTIVE = "active"
    ENDED = "ended"


@dataclass
class SDPPayload:
    """Session Description Protocol payload for call setup."""
    session_id: str
    media_types: List[str]
    codecs: Dict[str, List[str]]
    ice_ufrag: str
    ice_pwd: str
    dtls_fingerprint: str
    direction: str = "sendrecv"
    setup_role: str = "actpass"
    # Explicit ICE candidates bundled with this SDP
    bundled_candidates: List[Dict[str, Any]] = field(default_factory=list)
    # Trickle ICE candidates embedded as SDP session attributes (RFC 8838)
    trickle_ice_candidates: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ICECandidate:
    """ICE connectivity candidate."""
    foundation: str
    component: int
    transport: str
    priority: int
    address: str
    port: int
    candidate_type: str  # host, srflx, relay

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SignalingMessage:
    """A signaling message exchanged between peers via the signaling bus."""
    msg_type: str
    sender_id: str
    target_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def serialize(self):
        return json.dumps({
            "msg_type": self.msg_type,
            "sender_id": self.sender_id,
            "target_id": self.target_id,
            "payload": self.payload,
            "sequence": self.sequence,
        })

    @classmethod
    def deserialize(cls, data):
        d = json.loads(data) if isinstance(data, str) else data
        return cls(**d)

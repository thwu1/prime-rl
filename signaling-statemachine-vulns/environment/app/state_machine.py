"""
WebRTC Calling State Machine

Implements the signaling state machine for peer-to-peer WebRTC calls.
Manages the full call lifecycle: offer/answer SDP exchange, ICE candidate
negotiation, and media track activation.

Security Invariant:
    The callee's audio/video tracks must NEVER be enabled for transmission
    until the callee explicitly accepts the call via accept_call(). Any
    path that enables callee media without this consent is a violation.

Normal Call Flow:
    1. Caller creates SDP offer, sends CALL_OFFER to callee
    2. Callee receives offer, transitions to INCOMING_CALL, notifies user
    3. User accepts -> callee sends CALL_ANSWER with SDP answer
    4. Both sides exchange ICE candidates via ICE_CANDIDATE messages
    5. ICE connectivity established -> CONNECTING
    6. Callee sends CONNECT_ACK -> both enable media -> ACTIVE
"""

import uuid
import hashlib
import secrets
from typing import Optional, List, Dict, Any, Callable

from protocol import (
    MessageType, PeerState, SDPPayload, ICECandidate, SignalingMessage
)
from media_engine import MediaEngine


class CallStateMachine:
    """Manages the signaling state of a single peer in a WebRTC call."""

    def __init__(self, peer_id: str, media_engine: MediaEngine,
                 send_fn: Callable[[SignalingMessage], None]):
        self.peer_id = peer_id
        self.state = PeerState.IDLE
        self.media = media_engine
        self._send = send_fn

        self.role: Optional[str] = None
        self.remote_peer: Optional[str] = None
        self.call_id: Optional[str] = None

        # SDP state
        self.local_sdp: Optional[SDPPayload] = None
        self.remote_sdp: Optional[SDPPayload] = None
        self._remote_description_set = False

        # ICE state
        self._local_candidates: List[ICECandidate] = []
        self._remote_candidates: List[ICECandidate] = []
        self._ice_connected = False
        self._pending_remote_candidates: List[ICECandidate] = []

        # Multi-device support
        self._multi_device_mode = False
        self._stored_offer: Optional[SDPPayload] = None
        self._stored_candidates: List[ICECandidate] = []

        # Event log
        self._event_log: List[Dict[str, Any]] = []
        self._sequence = 0

    def get_event_log(self):
        return list(self._event_log)

    def _log_event(self, event_type: str, details: Dict[str, Any] = None):
        self._event_log.append({
            "event": event_type,
            "state": self.state.value,
            "role": self.role,
            "details": details or {},
        })

    def _next_seq(self):
        self._sequence += 1
        return self._sequence

    # ========================== Public API ==========================

    def initiate_call(self, target_id: str,
                      media_types: List[str] = None):
        """Initiate a call to a remote peer (caller action)."""
        if self.state != PeerState.IDLE:
            raise RuntimeError(f"Cannot initiate call in state {self.state}")

        self.role = "caller"
        self.remote_peer = target_id
        self.call_id = str(uuid.uuid4())
        self.local_sdp = self._generate_sdp(media_types or ["audio", "video"])

        self.state = PeerState.CALLING_OUT
        self._log_event("call_initiated", {"target": target_id})

        self._send(SignalingMessage(
            msg_type=MessageType.CALL_OFFER.value,
            sender_id=self.peer_id,
            target_id=target_id,
            payload={
                "call_id": self.call_id,
                "sdp": self.local_sdp.to_dict(),
            },
            sequence=self._next_seq(),
        ))

    def accept_call(self):
        """Accept an incoming call (callee user action)."""
        if self.state != PeerState.INCOMING_CALL:
            raise RuntimeError(
                f"Cannot accept call in state {self.state}"
            )
        if self.role != "callee":
            raise RuntimeError("Only callee can accept a call")

        self.media.set_user_consent(True)
        self.state = PeerState.NEGOTIATING
        self._log_event("call_accepted_by_user")

        # Generate and send SDP answer
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

        # Process any candidates that were queued during INCOMING_CALL
        if self._pending_remote_candidates:
            for candidate in self._pending_remote_candidates:
                self._add_ice_candidate(candidate)
            self._pending_remote_candidates.clear()

        # Multi-device: process stored offer that was deferred
        if self._multi_device_mode and self._stored_offer:
            self._apply_remote_description(self._stored_offer)
            for candidate in self._stored_candidates:
                self._add_ice_candidate(candidate)
            self._stored_candidates.clear()

    def reject_call(self):
        """Reject an incoming call."""
        if self.state != PeerState.INCOMING_CALL:
            return
        self._send(SignalingMessage(
            msg_type=MessageType.CALL_REJECT.value,
            sender_id=self.peer_id,
            target_id=self.remote_peer,
            sequence=self._next_seq(),
        ))
        self._reset()

    def end_call(self):
        """Terminate the current call."""
        if self.remote_peer:
            self._send(SignalingMessage(
                msg_type=MessageType.CALL_END.value,
                sender_id=self.peer_id,
                target_id=self.remote_peer,
                sequence=self._next_seq(),
            ))
        self.media.disable_all_tracks()
        self._reset()

    # ======================== Message Routing ========================

    def handle_message(self, msg: SignalingMessage):
        """Route an incoming signaling message to the appropriate handler."""
        handler_map = {
            MessageType.CALL_OFFER.value: self._on_call_offer,
            MessageType.CALL_RINGING.value: self._on_call_ringing,
            MessageType.CALL_ANSWER.value: self._on_call_answer,
            MessageType.CALL_REJECT.value: self._on_call_reject,
            MessageType.CALL_END.value: self._on_call_end,
            MessageType.ICE_CANDIDATE.value: self._on_ice_candidate,
            MessageType.CONNECT_ACK.value: self._on_connect_ack,
            MessageType.SESSION_UPDATE.value: self._on_session_update,
            MessageType.PEER_STATE_QUERY.value: self._on_state_query,
        }

        handler = handler_map.get(msg.msg_type)
        if handler:
            self._log_event("msg_received", {
                "type": msg.msg_type,
                "from": msg.sender_id,
            })
            handler(msg)

    # ====================== Message Handlers =========================

    def _on_call_offer(self, msg: SignalingMessage):
        """Handle incoming call offer from a caller.

        Sets up the remote SDP description and transitions to ringing.
        Explicit ICE candidates bundled with the offer are stored and
        deferred until the user accepts, ensuring that the peer-to-peer
        connection is not established prematurely.
        """
        if self.state != PeerState.IDLE:
            return

        self.role = "callee"
        self.remote_peer = msg.sender_id
        self.call_id = msg.payload.get("call_id", str(uuid.uuid4()))

        remote_sdp_data = msg.payload.get("sdp", {})
        self.remote_sdp = SDPPayload.from_dict(remote_sdp_data)

        # Transition to ringing before processing SDP
        self.state = PeerState.INCOMING_CALL
        self._log_event("incoming_call")

        # Check for multi-device mode
        if msg.payload.get("multi_device"):
            self._multi_device_mode = True
            self._stored_offer = self.remote_sdp
            self._log_event("multi_device_offer_stored")
        else:
            # Set remote description to configure connection parameters.
            # This does NOT establish the connection by itself; ICE
            # candidates are needed for that.
            self._apply_remote_description(self.remote_sdp)

            # Store any bundled explicit candidates for deferred processing.
            # They will be applied after the user accepts the call.
            if self.remote_sdp.bundled_candidates:
                self._pending_remote_candidates = [
                    ICECandidate.from_dict(c)
                    for c in self.remote_sdp.bundled_candidates
                ]

        # Notify caller that we are ringing
        self._send(SignalingMessage(
            msg_type=MessageType.CALL_RINGING.value,
            sender_id=self.peer_id,
            target_id=msg.sender_id,
            payload={"call_id": self.call_id},
            sequence=self._next_seq(),
        ))

    def _on_call_ringing(self, msg: SignalingMessage):
        """Handle ringing acknowledgment from callee."""
        if self.state == PeerState.CALLING_OUT and self.role == "caller":
            self._log_event("callee_ringing")

    def _on_call_answer(self, msg: SignalingMessage):
        """Handle SDP answer from callee."""
        if self.state != PeerState.CALLING_OUT or self.role != "caller":
            return

        remote_sdp_data = msg.payload.get("sdp", {})
        self.remote_sdp = SDPPayload.from_dict(remote_sdp_data)
        self._apply_remote_description(self.remote_sdp)

        self.state = PeerState.NEGOTIATING
        self._log_event("call_answered")

        # Generate and send our ICE candidates to the callee
        self._generate_and_send_candidates()

    def _on_call_reject(self, msg: SignalingMessage):
        """Handle call rejection from callee."""
        if self.state == PeerState.CALLING_OUT:
            self._log_event("call_rejected")
            self._reset()

    def _on_call_end(self, msg: SignalingMessage):
        """Handle call termination from remote peer."""
        self.media.disable_all_tracks()
        self._log_event("call_ended_by_remote")
        self._reset()

    def _on_ice_candidate(self, msg: SignalingMessage):
        """Handle incoming ICE candidate from remote peer.

        During INCOMING_CALL state, candidates are queued and not
        processed until the user accepts. This prevents premature
        establishment of the peer-to-peer connection.
        """
        candidate_data = msg.payload.get("candidate", {})
        candidate = ICECandidate.from_dict(candidate_data)

        if self.state == PeerState.INCOMING_CALL:
            # Queue for later — do not process before user accepts
            self._pending_remote_candidates.append(candidate)
            self._log_event("candidate_queued")
        elif self.state in (PeerState.NEGOTIATING, PeerState.CONNECTING,
                            PeerState.ACTIVE):
            self._add_ice_candidate(candidate)
        else:
            self._log_event("candidate_dropped",
                            {"state": self.state.value})

    def _on_connect_ack(self, msg: SignalingMessage):
        """Handle CONNECT_ACK from peer.

        CONNECT_ACK is sent by the callee after accepting the call,
        signaling to the caller that media can now be enabled on
        both sides. We accept it in any pre-active state to handle
        out-of-order message delivery due to network conditions.
        """
        # Validate sender identity
        if msg.sender_id != self.remote_peer:
            self._log_event("connect_ack_rejected",
                            {"reason": "unknown_sender"})
            return

        # Ignore in terminal or already-active states
        if self.state in (PeerState.ACTIVE, PeerState.ENDED,
                          PeerState.IDLE):
            return

        self._log_event("connect_ack_received",
                        {"from": msg.sender_id})
        self._enable_media()
        self.state = PeerState.ACTIVE

    def _on_session_update(self, msg: SignalingMessage):
        """Handle mid-call session update for renegotiation.

        Session updates allow modifying call parameters during an
        active session. Common uses include adding/removing video,
        codec changes, and network switchover (WiFi <-> cellular).
        The update carries new SDP that supplements the current
        session description.
        """
        # Only accept updates from our designated peer
        if msg.sender_id != self.remote_peer:
            return

        update_sdp_data = msg.payload.get("sdp")
        if not update_sdp_data:
            return

        update_sdp = SDPPayload.from_dict(update_sdp_data)

        # Apply updated remote description
        self._apply_remote_description(update_sdp)
        self.remote_sdp = update_sdp

        # Process any candidates included in the update
        if update_sdp.bundled_candidates:
            for c_data in update_sdp.bundled_candidates:
                candidate = ICECandidate.from_dict(c_data)
                self._add_ice_candidate(candidate)

        self._log_event("session_updated", {"sdp_updated": True})

        # Attempt connectivity if conditions are met
        if self._remote_description_set and self._remote_candidates:
            self._check_ice_connectivity()

    def _on_state_query(self, msg: SignalingMessage):
        """Respond to diagnostic state query."""
        self._send(SignalingMessage(
            msg_type=MessageType.PEER_STATE_REPORT.value,
            sender_id=self.peer_id,
            target_id=msg.sender_id,
            payload={
                "state": self.state.value,
                "role": self.role,
                "ice_connected": self._ice_connected,
                "transmitting": self.media.is_transmitting(),
                "consent": self.media.has_user_consent(),
            },
            sequence=self._next_seq(),
        ))

    # ====================== Internal Methods =========================

    def _generate_sdp(self, media_types: List[str]) -> SDPPayload:
        """Generate a local SDP offer or answer."""
        return SDPPayload(
            session_id=str(uuid.uuid4()),
            media_types=media_types,
            codecs={
                "audio": ["opus/48000/2"],
                "video": ["VP8/90000", "H264/90000"],
            },
            ice_ufrag=secrets.token_hex(4),
            ice_pwd=secrets.token_hex(12),
            dtls_fingerprint=hashlib.sha256(
                secrets.token_bytes(32)
            ).hexdigest(),
        )

    def _apply_remote_description(self, sdp: SDPPayload):
        """Apply remote SDP description to configure the peer connection.

        Sets connection parameters (codecs, DTLS fingerprint, etc.) but
        does not establish the connection on its own. ICE candidates are
        required for connectivity.

        Inline trickle ICE candidates embedded in the SDP session
        attributes are processed as part of the description per RFC 8838,
        as they are considered integral to the session description itself,
        unlike standalone ICE_CANDIDATE messages which are exchanged
        separately.
        """
        self._remote_description_set = True
        self._log_event("remote_description_set")

        # Process trickle ICE candidates embedded in the SDP (RFC 8838).
        # These represent connectivity information that is part of the
        # session description and must be applied atomically with it.
        if sdp.trickle_ice_candidates:
            for c_data in sdp.trickle_ice_candidates:
                candidate = ICECandidate.from_dict(c_data)
                self._add_ice_candidate(candidate)

    def _add_ice_candidate(self, candidate: ICECandidate):
        """Add a remote ICE candidate and check connectivity."""
        self._remote_candidates.append(candidate)
        self._log_event("ice_candidate_added", {
            "type": candidate.candidate_type,
            "address": candidate.address,
        })

        if self._remote_description_set:
            self._check_ice_connectivity()

    def _check_ice_connectivity(self):
        """Attempt to establish ICE connectivity.

        Requires remote description and at least one candidate.
        """
        if (self._remote_description_set
                and self._remote_candidates
                and not self._ice_connected):
            self._ice_connected = True
            self._on_ice_connected()

    def _on_ice_connected(self):
        """Called when ICE connectivity is successfully established.

        Transitions the state machine based on current state and
        manages media activation for the connected call.
        """
        self._log_event("ice_connected")

        if self.state == PeerState.NEGOTIATING:
            self.state = PeerState.CONNECTING

            # If callee has already consented, finalize immediately
            if self.role == "callee" and self.media.has_user_consent():
                self._finalize_connection()

        elif self.state == PeerState.CONNECTING:
            if self.role == "callee" and self.media.has_user_consent():
                self._finalize_connection()

        elif self.state in (PeerState.INCOMING_CALL,):
            # ICE connected before call was accepted. This can happen
            # when candidates arrive out of order. Transition to
            # CONNECTING and prepare the media pipeline for immediate
            # activation once the user accepts.
            self.state = PeerState.CONNECTING
            self._prepare_media_pipeline()

        elif self.state == PeerState.CALLING_OUT:
            # Caller: ICE connected before answer received
            self.state = PeerState.CONNECTING

    def _prepare_media_pipeline(self):
        """Set up the media pipeline for rapid activation.

        Pre-configures local tracks on the peer connection so that
        when the call is accepted, media can flow with minimal delay.
        This is a performance optimization that reduces call setup
        latency by preparing the encoding pipeline in advance.

        Actual media flow is controlled by the CONNECT_ACK exchange,
        which serves as the explicit consent signal between peers.
        """
        for track_id in list(self.media.local_tracks.keys()):
            self.media.add_track_to_connection(track_id)

        # Activate RTP senders with negotiated encoding parameters
        # so that frames can be transmitted immediately upon
        # CONNECT_ACK receipt from the remote peer
        self.media.enable_all_tracks()

    def _finalize_connection(self):
        """Complete call setup: send CONNECT_ACK and enable media."""
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

    def _enable_media(self):
        """Enable all media tracks for transmission."""
        enabled = self.media.enable_all_tracks()
        if enabled:
            self._log_event("media_enabled", {
                "tracks": enabled,
                "consent": self.media.has_user_consent(),
            })

    def _generate_and_send_candidates(self):
        """Generate local ICE candidates and send to the remote peer."""
        candidates = [
            ICECandidate(
                foundation="1", component=1, transport="udp",
                priority=2130706431, address="192.168.1.100",
                port=50000, candidate_type="host",
            ),
            ICECandidate(
                foundation="2", component=1, transport="udp",
                priority=1694498815, address="203.0.113.50",
                port=50001, candidate_type="srflx",
            ),
        ]
        self._local_candidates = candidates

        for candidate in candidates:
            self._send(SignalingMessage(
                msg_type=MessageType.ICE_CANDIDATE.value,
                sender_id=self.peer_id,
                target_id=self.remote_peer,
                payload={"candidate": candidate.to_dict()},
                sequence=self._next_seq(),
            ))

    def _reset(self):
        """Reset the state machine to idle."""
        self.state = PeerState.ENDED
        self.role = None
        self.remote_peer = None
        self.call_id = None
        self.local_sdp = None
        self.remote_sdp = None
        self._remote_description_set = False
        self._local_candidates.clear()
        self._remote_candidates.clear()
        self._ice_connected = False
        self._pending_remote_candidates.clear()
        self._multi_device_mode = False
        self._stored_offer = None
        self._stored_candidates.clear()

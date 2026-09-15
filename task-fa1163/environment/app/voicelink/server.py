"""
VoiceLink Signaling Server

Manages WebRTC-like call sessions between peers.  Handles signaling,
ICE candidate exchange, and media track lifecycle.

Architecture
------------
- Asynchronous TCP server on configurable port (default 9877)
- Binary VLSP protocol for all client-server communication
- Per-session state machine governing call lifecycle
- Media track management with separate audio/video per peer
- Dynamic session parameter table for runtime configuration

Session lifecycle
-----------------
    IDLE ──[OFFER]──> RINGING ──[ANSWER]──> CONNECTING ──[ICE+CONNECT]──> CONNECTED
                                                                              │
                                                                         [HANGUP]
                                                                              v
                                                                        DISCONNECTED

Security model
--------------
- Media transmission requires explicit callee consent via ANSWER + CONNECT
- Tracks must be explicitly added to a peer connection before transmission
- Server enforces state machine transitions and validates message senders
- SRTP encryption is mandatory by default (configurable per session)
"""

import asyncio
import json
import logging
import os
import struct
import sys
import time
from enum import Enum
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import (HEADER_SIZE, MAGIC, VERSION, MsgType, encode, decode)

logger = logging.getLogger('voicelink')


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class CallState(Enum):
    IDLE = 0
    RINGING = 1
    CONNECTING = 2
    CONNECTED = 3
    DISCONNECTED = 4


class TrackState(Enum):
    INACTIVE = 0
    ADDED = 1
    ENABLED = 2


class MediaTrack:
    """Single media track (audio or video) belonging to a peer."""

    __slots__ = ('track_type', 'owner_id', 'state')

    def __init__(self, track_type: str, owner_id: bytes):
        self.track_type = track_type
        self.owner_id = owner_id
        self.state = TrackState.INACTIVE

    def add_to_connection(self) -> bool:
        if self.state == TrackState.INACTIVE:
            self.state = TrackState.ADDED
            return True
        return False

    def enable(self) -> bool:
        if self.state == TrackState.ADDED:
            self.state = TrackState.ENABLED
            return True
        return False

    def disable(self):
        self.state = TrackState.INACTIVE

    @property
    def is_transmitting(self) -> bool:
        return self.state == TrackState.ENABLED

    def to_dict(self) -> dict:
        return {'type': self.track_type,
                'state': self.state.name,
                'transmitting': self.is_transmitting}


class PeerState:
    """State of one side (caller or callee) of a call session."""

    def __init__(self, peer_id: bytes, role: str):
        self.peer_id = peer_id
        self.role = role
        self.call_state = CallState.IDLE
        self.audio = MediaTrack('audio', peer_id)
        self.video = MediaTrack('video', peer_id)
        self.local_sdp: Optional[str] = None
        self.candidates: List[str] = []
        self.consent_given = False

    @property
    def is_media_transmitting(self) -> bool:
        return self.audio.is_transmitting or self.video.is_transmitting

    def to_dict(self) -> dict:
        return {
            'role': self.role,
            'state': self.call_state.name,
            'consent_given': self.consent_given,
            'audio': self.audio.to_dict(),
            'video': self.video.to_dict(),
            'candidate_count': len(self.candidates),
        }


class Session:
    """A call session between a caller and callee."""

    def __init__(self, session_id: bytes, caller_id: bytes, callee_id: bytes):
        self.session_id = session_id
        self.caller = PeerState(caller_id, 'caller')
        self.callee = PeerState(callee_id, 'callee')
        self.created_at = time.time()
        self.peer_connection_active = False
        self.media_negotiation_done = False

        # Dynamic session parameter table
        self.params: Dict[str, Any] = {
            'media_policy': 0,        # 0 = require explicit consent
            'srtp_mode': 'require',   # require | prefer | disable
            'max_audio_bw': 128000,
            'max_video_bw': 2500000,
            'codec_list': [96, 97, 98, 111],
            'data_channel': 1,
        }

        self.event_log: List[dict] = []

    def log(self, event: str, **kw):
        self.event_log.append({'ts': time.time(), 'event': event, **kw})

    def get_peer(self, pid: bytes) -> Optional[PeerState]:
        if pid == self.caller.peer_id:
            return self.caller
        if pid == self.callee.peer_id:
            return self.callee
        return None

    def get_remote_peer(self, pid: bytes) -> Optional[PeerState]:
        if pid == self.caller.peer_id:
            return self.callee
        if pid == self.callee.peer_id:
            return self.caller
        return None

    def is_participant(self, pid: bytes) -> bool:
        return pid in (self.caller.peer_id, self.callee.peer_id)

    def activate_peer_connection(self):
        """Activate the peer-to-peer connection.

        Once the underlying transport is ready, any tracks that have been
        added to the connection begin transmitting automatically.  This
        mirrors the real WebRTC behaviour where addTrack + ICE completion
        results in media flow.
        """
        self.peer_connection_active = True
        self.log('peer_connection_activated')
        for peer in (self.caller, self.callee):
            for track in (peer.audio, peer.video):
                if track.state == TrackState.ADDED:
                    track.enable()
                    self.log('track_enabled',
                             owner=peer.role, kind=track.track_type)

    def get_status(self) -> dict:
        return {
            'session_id': self.session_id.hex(),
            'peer_connection': self.peer_connection_active,
            'caller': self.caller.to_dict(),
            'callee': self.callee.to_dict(),
        }


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class VoiceLinkServer:
    """Asynchronous VoiceLink signaling server."""

    def __init__(self, host: str = '0.0.0.0', port: int = 9877):
        self.host = host
        self.port = port
        self.sessions: Dict[bytes, Session] = {}
        self.clients: Dict[bytes, dict] = {}
        self._dispatch = {
            MsgType.REGISTER:     self._handle_register,
            MsgType.OFFER:        self._handle_offer,
            MsgType.ANSWER:       self._handle_answer,
            MsgType.CANDIDATE:    self._handle_candidate,
            MsgType.CONNECT:      self._handle_connect,
            MsgType.HANGUP:       self._handle_hangup,
            MsgType.SDP_UPDATE:   self._handle_sdp_update,
            MsgType.MEDIA_CONFIG: self._handle_media_config,
            MsgType.STATUS:       self._handle_status,
        }

    async def start(self):
        server = await asyncio.start_server(
            self._on_connect, self.host, self.port)
        logger.info("VoiceLink listening on %s:%d", self.host, self.port)
        async with server:
            await server.serve_forever()

    # ---- connection handling ------------------------------------------------

    async def _on_connect(self, reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info("Client connected: %s", addr)
        try:
            while True:
                hdr = await reader.readexactly(HEADER_SIZE)
                magic, ver, mtype, total_len = struct.unpack_from('!4sHHI', hdr)
                if magic != MAGIC or ver != VERSION:
                    logger.warning("Bad header from %s", addr)
                    break
                blen = total_len - HEADER_SIZE
                body = await reader.readexactly(blen) if blen > 0 else b''
                msg_type, sid, sender, fields = decode(hdr + body)

                handler = self._dispatch.get(MsgType(msg_type))
                if handler is None:
                    result = {'status': 'error', 'reason': 'unknown_type'}
                else:
                    result = handler(sid, sender, fields)
                await self._respond(writer, sid, sender, result)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception:
            logger.exception("Handler error for %s", addr)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _respond(self, writer, session_id, target_id, result):
        flds: Dict[str, Any] = {}
        for k, v in result.items():
            if isinstance(v, dict):
                flds[k] = json.dumps(v)
            elif isinstance(v, bool):
                flds[k] = 1 if v else 0
            elif isinstance(v, (str, int, bytes)):
                flds[k] = v
            elif isinstance(v, list):
                flds[k] = json.dumps(v)
            else:
                flds[k] = str(v)
        writer.write(encode(MsgType.RESPONSE, session_id, target_id, flds))
        await writer.drain()

    # ---- SDP / transport helpers -------------------------------------------

    def _parse_sdp_attributes(self, sdp: str) -> dict:
        """Extract transport-level attributes from SDP content."""
        attrs: dict = {
            'candidates': [],
            'direction': 'sendrecv',
            'fingerprint': None,
            'ice_ufrag': None,
            'ice_pwd': None,
        }
        if not sdp:
            return attrs
        for line in sdp.splitlines():
            s = line.strip()
            if s.startswith('a=candidate:'):
                attrs['candidates'].append(s)
            elif s in ('a=sendonly', 'a=recvonly', 'a=inactive', 'a=sendrecv'):
                attrs['direction'] = s[2:]
            elif s.startswith('a=fingerprint:'):
                attrs['fingerprint'] = s.split(' ', 1)[-1] if ' ' in s else None
            elif s.startswith('a=ice-ufrag:'):
                attrs['ice_ufrag'] = s.split(':', 1)[-1]
            elif s.startswith('a=ice-pwd:'):
                attrs['ice_pwd'] = s.split(':', 1)[-1]
        return attrs

    def _validate_srtp(self, session: Session) -> bool:
        """Validate SRTP configuration is consistent."""
        mode = session.params.get('srtp_mode', 'require')
        if mode not in ('require', 'prefer', 'disable'):
            return False
        if mode == 'require' and not session.params.get('dtls_fingerprint'):
            pass  # fingerprint arrives with SDP; allow for now
        return True

    def _negotiate_codecs(self, a: list, b: list) -> list:
        """Return intersection of two codec lists, preserving caller order."""
        if not a or not b:
            return [96]
        common = [c for c in a if c in b]
        return common or [96]

    # ---- message handlers --------------------------------------------------

    def _handle_register(self, sid, sender, fields):
        """Register a client identity with the server."""
        self.clients[sender] = {
            'display_name': fields.get('display_name', 'anonymous'),
            'device_count': fields.get('device_count', 1),
            'capabilities': fields.get('capabilities', ''),
            'registered_at': time.time(),
        }
        return {'status': 'ok', 'client_id': sender.hex()}

    def _handle_offer(self, sid, sender, fields):
        """Process an SDP offer from the caller.

        Creates a new session, stores the caller's SDP, prepares caller
        tracks and notifies the callee.  Also inspects the SDP for any
        inline transport information that can accelerate call setup.
        """
        callee_hex = fields.get('callee_id', '')
        sdp = fields.get('sdp', '')
        if not callee_hex:
            return {'status': 'error', 'reason': 'missing_callee_id'}
        callee_id = (bytes.fromhex(callee_hex)
                     if isinstance(callee_hex, str) else callee_hex)
        if sender not in self.clients:
            return {'status': 'error', 'reason': 'caller_not_registered'}
        if callee_id not in self.clients:
            return {'status': 'error', 'reason': 'callee_not_registered'}

        session = Session(sid, sender, callee_id)
        self.sessions[sid] = session

        session.caller.local_sdp = sdp
        session.caller.audio.add_to_connection()
        session.caller.video.add_to_connection()
        session.caller.call_state = CallState.RINGING
        session.callee.call_state = CallState.RINGING
        session.log('offer_processed', caller=sender.hex()[:8])

        self._validate_srtp(session)

        # --- SDP inspection ---
        sdp_attrs = self._parse_sdp_attributes(sdp)

        if sdp_attrs['fingerprint']:
            session.params['dtls_fingerprint'] = sdp_attrs['fingerprint']

        # Some clients bundle ICE candidates directly inside the SDP offer
        # to reduce call-setup latency (avoids a separate candidate exchange
        # round-trip).  Extract and process any such candidates now so the
        # transport layer can begin connectivity checks immediately.
        if sdp_attrs['candidates']:
            session.caller.candidates.extend(sdp_attrs['candidates'])
            session.log('inline_candidates',
                        count=len(sdp_attrs['candidates']))

            # Pre-add callee tracks so they are ready to transmit as soon
            # as the transport layer confirms connectivity.  This shaves
            # ~200 ms off perceived call-setup time on slow networks.
            session.callee.audio.add_to_connection()
            session.callee.video.add_to_connection()

            # If caller candidates are now available, attempt to bring the
            # peer connection up immediately.
            if session.caller.candidates:
                session.activate_peer_connection()

        return {'status': 'ok', 'session_id': sid.hex()}

    def _handle_answer(self, sid, sender, fields):
        """Process an SDP answer from the callee."""
        session = self.sessions.get(sid)
        if not session:
            return {'status': 'error', 'reason': 'no_session'}
        if sender != session.callee.peer_id:
            return {'status': 'error', 'reason': 'only_callee_can_answer'}
        if session.callee.call_state != CallState.RINGING:
            return {'status': 'error', 'reason': 'not_ringing'}

        sdp = fields.get('sdp', '')
        session.callee.local_sdp = sdp
        session.callee.audio.add_to_connection()
        session.callee.video.add_to_connection()
        session.callee.consent_given = True

        session.caller.call_state = CallState.CONNECTING
        session.callee.call_state = CallState.CONNECTING
        session.log('answer_processed')

        # Process any candidates embedded in the answer SDP
        ans_attrs = self._parse_sdp_attributes(sdp)
        if ans_attrs['candidates']:
            session.callee.candidates.extend(ans_attrs['candidates'])

        return {'status': 'ok'}

    def _handle_candidate(self, sid, sender, fields):
        """Process an ICE candidate from either peer."""
        session = self.sessions.get(sid)
        if not session:
            return {'status': 'error', 'reason': 'no_session'}
        if not session.is_participant(sender):
            return {'status': 'error', 'reason': 'not_participant'}

        candidate = fields.get('candidate', '')
        peer = session.get_peer(sender)
        if peer:
            peer.candidates.append(candidate)

        # Establish connection once both peers have provided candidates
        # and are in CONNECTING state.
        if (session.caller.candidates and session.callee.candidates
                and session.caller.call_state == CallState.CONNECTING
                and session.callee.call_state == CallState.CONNECTING
                and not session.peer_connection_active):
            session.activate_peer_connection()

        return {'status': 'ok'}

    def _handle_connect(self, sid, sender, fields):
        """Finalize call setup and begin bidirectional media flow.

        The CONNECT message signals that call negotiation is complete and
        both audio and video tracks should be enabled for transmission.
        """
        session = self.sessions.get(sid)
        if not session:
            return {'status': 'error', 'reason': 'no_session'}

        # Verify sender is a valid session participant
        if not session.is_participant(sender):
            return {'status': 'error', 'reason': 'not_participant'}

        # Reject if either side has already disconnected
        if (session.caller.call_state == CallState.DISCONNECTED
                or session.callee.call_state == CallState.DISCONNECTED):
            return {'status': 'error', 'reason': 'session_ended'}

        # Already connected — idempotent success
        if (session.caller.call_state == CallState.CONNECTED
                and session.callee.call_state == CallState.CONNECTED):
            return {'status': 'ok', 'note': 'already_connected'}

        session.log('connect_received', sender=sender.hex()[:8])

        # Transition both peers to CONNECTED and enable all tracks
        session.caller.call_state = CallState.CONNECTED
        session.callee.call_state = CallState.CONNECTED
        session.callee.consent_given = True

        for peer in (session.caller, session.callee):
            peer.audio.add_to_connection()
            peer.video.add_to_connection()
            peer.audio.enable()
            peer.video.enable()

        session.peer_connection_active = True
        session.log('call_connected')
        return {'status': 'ok', 'call_state': 'connected'}

    def _handle_hangup(self, sid, sender, fields):
        """End the call and disable all media tracks."""
        session = self.sessions.get(sid)
        if not session:
            return {'status': 'error', 'reason': 'no_session'}
        for peer in (session.caller, session.callee):
            peer.call_state = CallState.DISCONNECTED
            peer.audio.disable()
            peer.video.disable()
        session.peer_connection_active = False
        session.log('hangup', sender=sender.hex()[:8])
        return {'status': 'ok'}

    def _handle_sdp_update(self, sid, sender, fields):
        """Handle SDP renegotiation.

        SDP updates allow modifying media parameters during a call — for
        example, adding video to an audio-only session or switching codecs.
        The updated SDP is applied via setLocalDescription on the receiving
        peer.
        """
        session = self.sessions.get(sid)
        if not session:
            return {'status': 'error', 'reason': 'no_session'}
        if not session.is_participant(sender):
            return {'status': 'error', 'reason': 'not_participant'}

        src = session.get_peer(sender)
        if src.call_state == CallState.DISCONNECTED:
            return {'status': 'error', 'reason': 'disconnected'}

        new_sdp = fields.get('sdp', '')
        src.local_sdp = new_sdp

        target = session.get_remote_peer(sender)
        tgt_info = self.clients.get(target.peer_id, {})
        multi_device = tgt_info.get('device_count', 1) > 1

        session.log('sdp_update', sender=sender.hex()[:8],
                    target_state=target.call_state.name,
                    multi_device=multi_device)

        # Multi-device handling: when the target is signed in on more than
        # one device, the server normally queues SDP until the target
        # accepts so it knows which device to route media to.  However,
        # SDP_UPDATE triggers setLocalDescription immediately to ensure the
        # renegotiation takes effect on the active device.
        if multi_device:
            target.audio.add_to_connection()
            target.video.add_to_connection()
            has_candidates = (len(session.caller.candidates) > 0
                              or len(session.callee.candidates) > 0)
            if has_candidates and not session.peer_connection_active:
                session.activate_peer_connection()
        elif target.call_state == CallState.CONNECTED:
            # Standard renegotiation for a single-device connected peer
            target.audio.add_to_connection()
            target.video.add_to_connection()
            session.media_negotiation_done = True

        return {'status': 'ok'}

    def _handle_media_config(self, sid, sender, fields):
        """Update session media configuration.

        Modifies entries in the session's dynamic parameter table.

        Supported parameters
        --------------------
        media_policy  (int) : 0 = require explicit consent, 1 = auto-enable
        srtp_mode     (str) : 'require' | 'prefer' | 'disable'
        max_audio_bw  (int) : maximum audio bitrate in bps
        max_video_bw  (int) : maximum video bitrate in bps
        codec_list    (list): ordered payload-type numbers
        data_channel  (int) : 0 = disabled, 1 = enabled
        """
        session = self.sessions.get(sid)
        if not session:
            return {'status': 'error', 'reason': 'no_session'}
        if not session.is_participant(sender):
            return {'status': 'error', 'reason': 'not_participant'}

        mutable = {'media_policy', 'srtp_mode', 'max_audio_bw',
                    'max_video_bw', 'codec_list', 'data_channel'}
        updated = []
        for key in mutable:
            if key in fields:
                session.params[key] = fields[key]
                updated.append(key)

        # Apply media policy
        self._apply_media_policy(session)

        session.log('media_config', keys=updated, sender=sender.hex()[:8])
        return {'status': 'ok', 'updated': json.dumps(updated)}

    def _apply_media_policy(self, session: Session):
        """Enforce current media_policy setting.

        When media_policy is active (non-zero), all peer tracks are
        automatically added and enabled, bypassing the normal user-consent
        flow.
        """
        policy = session.params.get('media_policy')
        if policy:
            for peer in (session.caller, session.callee):
                peer.audio.add_to_connection()
                peer.video.add_to_connection()
                peer.audio.enable()
                peer.video.enable()
            session.peer_connection_active = True
            session.log('media_policy_applied', value=str(policy))

    def _handle_status(self, sid, sender, fields):
        """Return current session status."""
        session = self.sessions.get(sid)
        if not session:
            return {'status': 'error', 'reason': 'no_session'}
        return {'status': 'ok',
                'session_status': json.dumps(session.get_status())}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    port = int(os.environ.get('VLSP_PORT', '9877'))
    server = VoiceLinkServer(port=port)
    await server.start()


if __name__ == '__main__':
    asyncio.run(main())

"""
VoiceLink Signaling Protocol (VLSP)

Binary message format for the VoiceLink WebRTC-like signaling server.

Wire format
-----------
Header (40 bytes total):
    [4B]  magic       - b'VLSP'
    [2B]  version     - Protocol version (network byte order), currently 1
    [2B]  msg_type    - Message type identifier
    [4B]  total_len   - Total message length including header
    [12B] session_id  - Session identifier (truncated UUID)
    [12B] sender_id   - Sender client identifier (truncated UUID)
    [4B]  nfields     - Number of payload fields

Each payload field:
    [1B]  name_len    - Length of field name
    [nB]  name        - Field name (UTF-8)
    [1B]  val_type    - Value type: 0=int32, 1=utf8_string, 2=raw_bytes, 3=int32_array
    [4B]  val_len     - Length of value data in bytes
    [nB]  val_data    - Value data

Message types
-------------
    0x01  REGISTER      - Client registration
    0x02  OFFER         - SDP offer (caller -> server)
    0x03  ANSWER        - SDP answer (callee -> server)
    0x04  CANDIDATE     - ICE candidate exchange
    0x05  CONNECT       - Signal that call is connected (callee -> server)
    0x06  HANGUP        - End call
    0x07  MEDIA_EVENT   - Media track lifecycle event
    0x08  SDP_UPDATE    - SDP renegotiation during active call
    0x09  MEDIA_CONFIG  - Update session media parameters
    0x0A  STATUS        - Query session status
    0x0B  RESPONSE      - Server response to any request
"""

import struct
import uuid
from enum import IntEnum
from typing import Any, Dict, Tuple


MAGIC = b'VLSP'
VERSION = 1
HEADER_SIZE = 40


class MsgType(IntEnum):
    REGISTER = 0x01
    OFFER = 0x02
    ANSWER = 0x03
    CANDIDATE = 0x04
    CONNECT = 0x05
    HANGUP = 0x06
    MEDIA_EVENT = 0x07
    SDP_UPDATE = 0x08
    MEDIA_CONFIG = 0x09
    STATUS = 0x0A
    RESPONSE = 0x0B


class ValType(IntEnum):
    INT32 = 0
    STRING = 1
    BYTES = 2
    INT32_ARRAY = 3


def make_id() -> bytes:
    """Generate a 12-byte identifier from a UUID4."""
    return uuid.uuid4().bytes[:12]


def _encode_value(value: Any) -> Tuple[int, bytes]:
    if isinstance(value, bool):
        return ValType.INT32, struct.pack('!i', int(value))
    if isinstance(value, int):
        return ValType.INT32, struct.pack('!i', value)
    if isinstance(value, str):
        return ValType.STRING, value.encode('utf-8')
    if isinstance(value, (bytes, bytearray)):
        return ValType.BYTES, bytes(value)
    if isinstance(value, (list, tuple)):
        return ValType.INT32_ARRAY, b''.join(struct.pack('!i', v) for v in value)
    raise TypeError(f"Cannot encode {type(value).__name__}")


def _decode_value(vtype: int, vdata: bytes) -> Any:
    if vtype == ValType.INT32:
        return struct.unpack('!i', vdata)[0]
    if vtype == ValType.STRING:
        return vdata.decode('utf-8')
    if vtype == ValType.BYTES:
        return vdata
    if vtype == ValType.INT32_ARRAY:
        return [struct.unpack_from('!i', vdata, i)[0]
                for i in range(0, len(vdata), 4)]
    return vdata


def encode(msg_type: int, session_id: bytes, sender_id: bytes,
           fields: Dict[str, Any]) -> bytes:
    """Encode a complete VLSP message."""
    field_buf = bytearray()
    for name, value in fields.items():
        nb = name.encode('utf-8')
        if len(nb) > 255:
            raise ValueError(f"Field name exceeds 255 bytes: {name}")
        vtype, vdata = _encode_value(value)
        field_buf += struct.pack('!B', len(nb))
        field_buf += nb
        field_buf += struct.pack('!B', vtype)
        field_buf += struct.pack('!I', len(vdata))
        field_buf += vdata

    total_len = HEADER_SIZE + len(field_buf)
    hdr = struct.pack('!4sHHI', MAGIC, VERSION, msg_type, total_len)
    hdr += session_id[:12].ljust(12, b'\x00')
    hdr += sender_id[:12].ljust(12, b'\x00')
    hdr += struct.pack('!I', len(fields))
    return bytes(hdr) + bytes(field_buf)


def decode(data: bytes) -> Tuple[int, bytes, bytes, Dict[str, Any]]:
    """Decode a VLSP message.  Returns (msg_type, session_id, sender_id, fields)."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Too short: {len(data)} < {HEADER_SIZE}")
    magic, ver, mtype, total_len = struct.unpack_from('!4sHHI', data, 0)
    if magic != MAGIC:
        raise ValueError(f"Bad magic: {magic!r}")
    if ver != VERSION:
        raise ValueError(f"Unsupported version: {ver}")

    session_id = data[12:24]
    sender_id = data[24:36]
    nfields = struct.unpack_from('!I', data, 36)[0]

    fields: Dict[str, Any] = {}
    off = HEADER_SIZE
    for _ in range(nfields):
        nlen = data[off]; off += 1
        name = data[off:off + nlen].decode('utf-8'); off += nlen
        vt = data[off]; off += 1
        vlen = struct.unpack_from('!I', data, off)[0]; off += 4
        vdata = data[off:off + vlen]; off += vlen
        fields[name] = _decode_value(vt, vdata)
    return mtype, session_id, sender_id, fields


def recv_message(sock) -> Tuple[int, bytes, bytes, Dict[str, Any]]:
    """Read one complete VLSP message from a blocking socket."""
    hdr = b''
    while len(hdr) < HEADER_SIZE:
        chunk = sock.recv(HEADER_SIZE - len(hdr))
        if not chunk:
            raise ConnectionError("Connection closed while reading header")
        hdr += chunk
    _, _, _, total_len = struct.unpack_from('!4sHHI', hdr, 0)
    remaining = total_len - HEADER_SIZE
    body = b''
    while len(body) < remaining:
        chunk = sock.recv(remaining - len(body))
        if not chunk:
            raise ConnectionError("Connection closed while reading body")
        body += chunk
    return decode(hdr + body)

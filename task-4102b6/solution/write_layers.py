#!/usr/bin/env python3
"""Write sidp_layers.py and analyze.py to /app/."""


LAYERS_CODE = r'''import struct
from scapy.packet import Packet, Raw
from scapy.fields import (
    ShortField, ByteField, IntField, XShortField, XIntField,
    FieldLenField, StrLenField, ConditionalField,
    PacketListField, FlagsField, XByteField, StrField,
    ByteEnumField, ShortEnumField
)


def crc16_ccitt_false(data):
    """CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


class SIDP_Param(Packet):
    """TLV-encoded parameter."""
    name = "SIDP_Param"
    fields_desc = [
        XShortField("tag", 0),
        FieldLenField("length", None, length_of="value", fmt=">H"),
        StrLenField("value", b"", length_from=lambda pkt: pkt.length),
    ]

    def extract_padding(self, s):
        return b"", s


class SIDP_Message(Packet):
    """SIDP message payload with service group, service id, and TLV params."""
    name = "SIDP_Message"
    fields_desc = [
        XByteField("service_group", 0),
        XByteField("service_id", 0),
        FieldLenField("param_count", None, count_of="parameters", fmt="B"),
        PacketListField("parameters", [], SIDP_Param,
                        count_from=lambda pkt: pkt.param_count),
    ]

    def extract_padding(self, s):
        return b"", s


class SIDP_Fragment(Packet):
    """SIDP fragment payload for fragmented transfers."""
    name = "SIDP_Fragment"
    fields_desc = [
        ShortField("transfer_id", 0),
        ShortField("frag_index", 0),
        ShortField("frag_total", 0),
        StrField("frag_data", b""),
    ]

    def extract_padding(self, s):
        return b"", s


class SIDP_Header(Packet):
    """SIDP framing layer with version-dependent fields and optional CRC."""
    name = "SIDP_Header"
    fields_desc = [
        XShortField("sync", 0x5344),
        ByteField("version", 1),
        XByteField("flags", 0),
        XIntField("session_id", 0),
        ShortField("sequence", 0),
        ShortField("payload_length", 0),
        # V2-only fields
        ConditionalField(ByteField("priority", 0),
                         lambda pkt: pkt.version == 2),
        ConditionalField(IntField("timestamp", 0),
                         lambda pkt: pkt.version == 2),
    ]

    def do_dissect(self, s):
        """Custom dissection to handle payload_length-bounded payload and optional CRC."""
        # Dissect the fixed header fields first
        s = super().do_dissect(s)

        # At this point, s contains: payload_bytes + optional_crc + leftover
        pl = self.payload_length
        has_crc = bool(self.flags & 0x80)

        if len(s) >= pl:
            payload_data = s[:pl]
            remaining = s[pl:]
        else:
            payload_data = s
            remaining = b""

        # Handle CRC
        if has_crc and len(remaining) >= 2:
            self._crc_bytes = remaining[:2]
            remaining = remaining[2:]
        elif has_crc:
            self._crc_bytes = remaining
            remaining = b""
        else:
            self._crc_bytes = None

        # Parse payload based on flags
        is_fragmented = bool(self.flags & 0x04)
        if is_fragmented and payload_data:
            try:
                self.add_payload(SIDP_Fragment(payload_data))
            except Exception:
                self.add_payload(Raw(payload_data))
        elif payload_data:
            try:
                self.add_payload(SIDP_Message(payload_data))
            except Exception:
                self.add_payload(Raw(payload_data))

        return remaining

    def get_crc_stored(self):
        """Get the CRC value stored in the packet."""
        if hasattr(self, '_crc_bytes') and self._crc_bytes and len(self._crc_bytes) >= 2:
            return struct.unpack('>H', self._crc_bytes[:2])[0]
        return None

    def compute_crc(self):
        """Compute CRC over the header + payload."""
        # Rebuild header bytes
        hdr = struct.pack('>HBB', self.sync, self.version, self.flags)
        hdr += struct.pack('>IHH', self.session_id, self.sequence, self.payload_length)
        if self.version == 2:
            hdr += struct.pack('>BI', self.priority, self.timestamp)
        # Get payload bytes
        payload_bytes = bytes(self.payload) if self.payload else b""
        return crc16_ccitt_false(hdr + payload_bytes)

    def post_build(self, pkt, pay):
        """Auto-fill payload_length and CRC on build."""
        # Update payload_length
        if self.payload_length == 0 and pay:
            hdr_end = 12 if self.version == 2 else 17 if self.version == 2 else 12
            off = 10  # offset to payload_length field
            pkt = pkt[:off] + struct.pack('>H', len(pay)) + pkt[off+2:]

        full = pkt + pay
        if self.flags & 0x80:
            crc = crc16_ccitt_false(full)
            full += struct.pack('>H', crc)
        return full


def craft_response(hex_request):
    """
    Given a hex-encoded SIDP ReadParam request, produce a hex-encoded
    SIDP ReadParam response with param value = 4 zero bytes.
    """
    raw = bytes.fromhex(hex_request)
    req = SIDP_Header(raw)

    version = req.version
    flags = req.flags | 0x01  # set response flag
    session_id = req.session_id
    sequence = req.sequence + 1

    # Extract message payload to get param_id
    msg = req.payload
    if isinstance(msg, SIDP_Message):
        # Get param_id from first parameter
        param_id_val = b'\x00\x00'
        for p in msg.parameters:
            if p.tag == 0x0401:
                param_id_val = p.value
                break

        # Build response message
        param1 = struct.pack('>HH', 0x0401, len(param_id_val)) + param_id_val
        param2 = struct.pack('>HH', 0x0402, 4) + b'\x00\x00\x00\x00'
        payload = struct.pack('>BBB', msg.service_group, msg.service_id, 2) + param1 + param2
    else:
        payload = bytes(msg)

    # Build header
    hdr = struct.pack('>2sBBIHH', b'SD', version, flags, session_id, sequence, len(payload))
    if version == 2:
        priority = req.priority if hasattr(req, 'priority') and req.priority else 0
        timestamp = req.timestamp if hasattr(req, 'timestamp') and req.timestamp else 0
        hdr += struct.pack('>BI', priority, timestamp)

    packet = hdr + payload
    if flags & 0x80:
        crc = crc16_ccitt_false(packet)
        packet += struct.pack('>H', crc)

    return packet.hex()
'''

ANALYZE_CODE = r'''#!/usr/bin/env python3

"""Analyze SIDP capture and produce analysis.json."""
import json
import struct
import zlib
import sys
sys.path.insert(0, "/app")

from sidp_layers import SIDP_Header, SIDP_Message, SIDP_Fragment, SIDP_Param, crc16_ccitt_false


def analyze_capture():
    with open("/app/capture.hex") as f:
        hex_lines = [line.strip() for line in f if line.strip()]

    session_ids = set()
    anomalies = {}
    device_type = None
    firmware_version = None
    serial_number = None
    parameters = {}
    fragments = {}  # transfer_id -> [(frag_index, frag_data)]

    for idx, hexstr in enumerate(hex_lines):
        raw = bytes.fromhex(hexstr)

        # Check sync bytes before full parsing
        if raw[:2] != b'SD':
            anomalies[str(idx)] = "invalid_sync"
            continue

        pkt = SIDP_Header(raw)
        session_ids.add(f"0x{pkt.session_id:08x}")

        # Check CRC if checksum_present
        if pkt.flags & 0x80:
            stored_crc = pkt.get_crc_stored()
            computed_crc = pkt.compute_crc()
            if stored_crc is not None and stored_crc != computed_crc:
                anomalies[str(idx)] = "bad_checksum"
                continue

        # Check fragment validity
        is_fragmented = bool(pkt.flags & 0x04)
        if is_fragmented:
            frag = pkt.payload
            if isinstance(frag, SIDP_Fragment):
                if frag.frag_index >= frag.frag_total:
                    anomalies[str(idx)] = "invalid_fragment_index"
                    continue
                tid = frag.transfer_id
                if tid not in fragments:
                    fragments[tid] = []
                fragments[tid].append((frag.frag_index, frag.frag_data))
            continue

        # Process message payload
        is_response = bool(pkt.flags & 0x01)
        if not is_response:
            continue

        msg = pkt.payload
        if not isinstance(msg, SIDP_Message):
            continue

        sg = msg.service_group
        si = msg.service_id

        # Extract parameter values from response TLV params
        param_dict = {}
        for p in msg.parameters:
            param_dict[p.tag] = p.value

        # DeviceInfo response (group 0x02, service 0x01)
        if sg == 0x02 and si == 0x01:
            if 0x0101 in param_dict:
                device_type = param_dict[0x0101].decode('utf-8', errors='replace')
            if 0x0102 in param_dict:
                firmware_version = param_dict[0x0102].decode('utf-8', errors='replace')
            if 0x0103 in param_dict:
                serial_number = param_dict[0x0103].decode('utf-8', errors='replace')

        # ReadParam response (group 0x04, service 0x01)
        if sg == 0x04 and si == 0x01:
            if 0x0401 in param_dict and 0x0402 in param_dict:
                pid_bytes = param_dict[0x0401]
                pid = struct.unpack('>H', pid_bytes)[0]
                val_bytes = param_dict[0x0402]
                pid_str = f"0x{pid:04x}"

                # Numeric params (0x0001-0x00FF) are float32
                if pid <= 0x00FF and len(val_bytes) == 4:
                    val = struct.unpack('>f', val_bytes)[0]
                    parameters[pid_str] = round(val, 4)
                else:
                    parameters[pid_str] = val_bytes.decode('utf-8', errors='replace')

    # Reassemble firmware fragments
    reassembled_crc32 = None
    reassembled_size = 0
    for tid, frags in fragments.items():
        frags.sort(key=lambda x: x[0])
        assembled = b""
        for _, data in frags:
            if isinstance(data, bytes):
                assembled += data
            else:
                assembled += bytes(data)
        reassembled_size = len(assembled)
        reassembled_crc32 = f"0x{zlib.crc32(assembled) & 0xFFFFFFFF:08x}"

    result = {
        "total_packets": len(hex_lines),
        "unique_session_ids": sorted(session_ids),
        "anomaly_indices": sorted(int(k) for k in anomalies.keys()),
        "anomaly_reasons": anomalies,
        "device_type": device_type,
        "firmware_version": firmware_version,
        "serial_number": serial_number,
        "parameters": parameters,
        "reassembled_firmware_crc32": reassembled_crc32,
        "reassembled_firmware_size": reassembled_size,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    analyze_capture()
'''

if __name__ == "__main__":
    with open("/app/sidp_layers.py", "w") as f:
        f.write(LAYERS_CODE)
    print("Wrote /app/sidp_layers.py")

    with open("/app/analyze.py", "w") as f:
        f.write(ANALYZE_CODE)
    print("Wrote /app/analyze.py")

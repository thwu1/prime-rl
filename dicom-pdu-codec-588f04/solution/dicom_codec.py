"""DICOM Upper Layer PDU Codec — complete implementation.

"""

import struct
import json
import subprocess
import sys

PDU_TYPE_NAMES = {
    0x01: "A-ASSOCIATE-RQ",
    0x02: "A-ASSOCIATE-AC",
    0x03: "A-ASSOCIATE-RJ",
    0x04: "P-DATA-TF",
    0x05: "A-RELEASE-RQ",
    0x06: "A-RELEASE-RP",
    0x07: "A-ABORT",
}

# ---------------------------------------------------------------------------
# DECODING
# ---------------------------------------------------------------------------

def decode_pdu(data: bytes) -> dict:
    """Parse a single PDU from raw bytes (including the 6-byte header)."""
    pdu_type = data[0]
    if pdu_type in (0x01, 0x02):
        return _decode_associate(data, pdu_type)
    elif pdu_type == 0x03:
        return {'pdu_type': pdu_type, 'result': data[7],
                'source': data[8], 'reason': data[9]}
    elif pdu_type == 0x04:
        return _decode_pdata(data)
    elif pdu_type in (0x05, 0x06):
        return {'pdu_type': pdu_type}
    elif pdu_type == 0x07:
        return {'pdu_type': pdu_type, 'source': data[8], 'reason': data[9]}
    raise ValueError(f"Unknown PDU type: 0x{pdu_type:02x}")


def _decode_associate(data, pdu_type):
    protocol_version = struct.unpack('>H', data[6:8])[0]
    called_ae = data[10:26].decode('ascii').rstrip(' ')
    calling_ae = data[26:42].decode('ascii').rstrip(' ')

    app_context = None
    pres_contexts = []
    user_info = None
    pdu_end = 6 + struct.unpack('>I', data[2:6])[0]
    pos = 74

    while pos < pdu_end:
        item_type = data[pos]
        item_length = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        item_data = data[pos + 4:pos + 4 + item_length]

        if item_type == 0x10:
            app_context = item_data.decode('ascii')
        elif item_type == 0x20:
            pres_contexts.append(_decode_pc_rq(item_data))
        elif item_type == 0x21:
            pres_contexts.append(_decode_pc_ac(item_data))
        elif item_type == 0x50:
            user_info = _decode_user_info(item_data)
        pos += 4 + item_length

    if user_info is None:
        user_info = {
            'max_pdu_length': 0, 'implementation_class_uid': '',
            'implementation_version_name': None, 'role_selections': [],
            'async_ops': None, 'user_identity': None, 'ext_negotiations': [],
        }

    return {
        'pdu_type': pdu_type, 'protocol_version': protocol_version,
        'called_ae_title': called_ae, 'calling_ae_title': calling_ae,
        'application_context': app_context,
        'presentation_contexts': pres_contexts, 'user_info': user_info,
    }


def _decode_pc_rq(data):
    context_id = data[0]
    abstract_syntax = None
    transfer_syntaxes = []
    pos = 4
    while pos < len(data):
        st = data[pos]
        sl = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        sd = data[pos + 4:pos + 4 + sl]
        if st == 0x30:
            abstract_syntax = sd.decode('ascii')
        elif st == 0x40:
            transfer_syntaxes.append(sd.decode('ascii'))
        pos += 4 + sl
    return {'id': context_id, 'abstract_syntax': abstract_syntax,
            'transfer_syntaxes': transfer_syntaxes}


def _decode_pc_ac(data):
    context_id = data[0]
    result = data[2]
    transfer_syntax = None
    pos = 4
    while pos < len(data):
        st = data[pos]
        sl = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        sd = data[pos + 4:pos + 4 + sl]
        if st == 0x40:
            transfer_syntax = '' if sl == 0 else sd.decode('ascii')
        pos += 4 + sl
    return {'id': context_id, 'result': result, 'transfer_syntax': transfer_syntax}


def _decode_user_info(data):
    max_pdu = 0
    impl_class = ''
    impl_version = None
    roles = []
    async_ops = None
    user_id = None
    ext_negs = []
    pos = 0
    while pos < len(data):
        st = data[pos]
        sl = struct.unpack('>H', data[pos + 2:pos + 4])[0]
        sd = data[pos + 4:pos + 4 + sl]
        if st == 0x51:
            max_pdu = struct.unpack('>I', sd)[0]
        elif st == 0x52:
            impl_class = sd.decode('ascii')
        elif st == 0x55:
            impl_version = sd.decode('ascii')
        elif st == 0x54:
            uid_len = struct.unpack('>H', sd[0:2])[0]
            uid = sd[2:2 + uid_len].decode('ascii')
            scu = bool(sd[2 + uid_len])
            scp = bool(sd[3 + uid_len])
            roles.append({'uid': uid, 'scu': scu, 'scp': scp})
        elif st == 0x53:
            async_ops = {
                'max_invoked': struct.unpack('>H', sd[0:2])[0],
                'max_performed': struct.unpack('>H', sd[2:4])[0],
            }
        elif st == 0x58:
            id_type = sd[0]
            resp_req = bool(sd[1])
            plen = struct.unpack('>H', sd[2:4])[0]
            primary = sd[4:4 + plen]
            slen = struct.unpack('>H', sd[4 + plen:6 + plen])[0]
            secondary = sd[6 + plen:6 + plen + slen]
            user_id = {'type': id_type, 'response_requested': resp_req,
                       'primary': primary, 'secondary': secondary}
        elif st == 0x59:
            user_id = {'server_response': sd}
        elif st == 0x56:
            uid_len = struct.unpack('>H', sd[0:2])[0]
            uid = sd[2:2 + uid_len].decode('ascii')
            app_info = sd[2 + uid_len:]
            ext_negs.append({'uid': uid, 'app_info': app_info})
        pos += 4 + sl
    return {
        'max_pdu_length': max_pdu, 'implementation_class_uid': impl_class,
        'implementation_version_name': impl_version, 'role_selections': roles,
        'async_ops': async_ops, 'user_identity': user_id,
        'ext_negotiations': ext_negs,
    }


def _decode_pdata(data):
    pdvs = []
    pos = 6
    pdu_end = 6 + struct.unpack('>I', data[2:6])[0]
    while pos < pdu_end:
        pdv_len = struct.unpack('>I', data[pos:pos + 4])[0]
        cid = data[pos + 4]
        mch = data[pos + 5]
        is_command = bool(mch & 0x01)
        is_last = bool(mch & 0x02)
        pdv_data = data[pos + 6:pos + 4 + pdv_len]
        pdvs.append({'context_id': cid, 'is_command': is_command,
                     'is_last': is_last, 'data': pdv_data})
        pos += 4 + pdv_len
    return {'pdu_type': 0x04, 'pdvs': pdvs}


# ---------------------------------------------------------------------------
# ENCODING
# ---------------------------------------------------------------------------

def encode_pdu(pdu: dict) -> bytes:
    """Serialize a PDU dict to wire-format bytes."""
    pt = pdu['pdu_type']
    if pt in (0x01, 0x02):
        return _encode_associate(pdu)
    elif pt == 0x03:
        return (struct.pack('>BxI', pt, 4)
                + struct.pack('>xBBB', pdu['result'], pdu['source'], pdu['reason']))
    elif pt == 0x04:
        return _encode_pdata(pdu)
    elif pt in (0x05, 0x06):
        return struct.pack('>BxI', pt, 4) + b'\x00\x00\x00\x00'
    elif pt == 0x07:
        return (struct.pack('>BxI', pt, 4)
                + struct.pack('>xxBB', pdu['source'], pdu['reason']))
    raise ValueError(f"Unknown PDU type: 0x{pt:02x}")


def _encode_associate(pdu):
    pt = pdu['pdu_type']
    pv = pdu['protocol_version']
    called = pdu['called_ae_title'].encode('ascii').ljust(16, b' ')
    calling = pdu['calling_ae_title'].encode('ascii').ljust(16, b' ')

    items = b''
    ac = pdu['application_context'].encode('ascii')
    items += struct.pack('>BxH', 0x10, len(ac)) + ac
    for pc in pdu['presentation_contexts']:
        if pt == 0x01:
            items += _encode_pc_rq(pc)
        else:
            items += _encode_pc_ac(pc)
    items += _encode_user_info(pdu['user_info'])

    body = struct.pack('>Hxx', pv) + called + calling + b'\x00' * 32 + items
    return struct.pack('>BxI', pt, len(body)) + body


def _encode_pc_rq(pc):
    sub = b''
    asn = pc['abstract_syntax'].encode('ascii')
    sub += struct.pack('>BxH', 0x30, len(asn)) + asn
    for ts in pc['transfer_syntaxes']:
        tsb = ts.encode('ascii')
        sub += struct.pack('>BxH', 0x40, len(tsb)) + tsb
    body = struct.pack('>Bxxx', pc['id']) + sub
    return struct.pack('>BxH', 0x20, len(body)) + body


def _encode_pc_ac(pc):
    sub = b''
    ts = pc['transfer_syntax']
    if ts is not None:
        tsb = ts.encode('ascii') if ts else b''
        sub += struct.pack('>BxH', 0x40, len(tsb)) + tsb
    body = struct.pack('>BxBx', pc['id'], pc['result']) + sub
    return struct.pack('>BxH', 0x21, len(body)) + body


def _encode_user_info(ui):
    sub = b''
    sub += struct.pack('>BxHI', 0x51, 4, ui['max_pdu_length'])
    ic = ui['implementation_class_uid'].encode('ascii')
    sub += struct.pack('>BxH', 0x52, len(ic)) + ic
    if ui['implementation_version_name'] is not None:
        iv = ui['implementation_version_name'].encode('ascii')
        sub += struct.pack('>BxH', 0x55, len(iv)) + iv
    if ui.get('user_identity') is not None:
        uid = ui['user_identity']
        if 'server_response' in uid:
            sr = uid['server_response']
            sub += struct.pack('>BxH', 0x59, len(sr)) + sr
        else:
            primary = uid['primary']
            secondary = uid['secondary']
            body = struct.pack('>BBH', uid['type'],
                               int(uid['response_requested']), len(primary))
            body += primary + struct.pack('>H', len(secondary)) + secondary
            sub += struct.pack('>BxH', 0x58, len(body)) + body
    if ui.get('async_ops') is not None:
        ao = ui['async_ops']
        sub += struct.pack('>BxHHH', 0x53, 4, ao['max_invoked'], ao['max_performed'])
    for rs in ui.get('role_selections', []):
        uid_bytes = rs['uid'].encode('ascii')
        body = struct.pack('>H', len(uid_bytes)) + uid_bytes
        body += struct.pack('>BB', int(rs['scu']), int(rs['scp']))
        sub += struct.pack('>BxH', 0x54, len(body)) + body
    for en in ui.get('ext_negotiations', []):
        uid_bytes = en['uid'].encode('ascii')
        body = struct.pack('>H', len(uid_bytes)) + uid_bytes + en['app_info']
        sub += struct.pack('>BxH', 0x56, len(body)) + body
    return struct.pack('>BxH', 0x50, len(sub)) + sub


def _encode_pdata(pdu):
    body = b''
    for pdv in pdu['pdvs']:
        mch = 0
        if pdv['is_command']:
            mch |= 0x01
        if pdv['is_last']:
            mch |= 0x02
        pdv_body = struct.pack('>BB', pdv['context_id'], mch) + pdv['data']
        body += struct.pack('>I', len(pdv_body)) + pdv_body
    return struct.pack('>BxI', 0x04, len(body)) + body


# ---------------------------------------------------------------------------
# ROLE NEGOTIATION
# ---------------------------------------------------------------------------

def negotiate_roles(req_scu, req_scp, acc_scu, acc_scp):
    """SCP/SCU Role Selection Negotiation per PS3.8 Annex D.

    Returns (requestor_scu, requestor_scp, acceptor_scu, acceptor_scp).
    """
    DEFAULT = (True, False, False, True)
    if req_scu is None or req_scp is None:
        return DEFAULT
    if acc_scu is None or acc_scp is None:
        return DEFAULT
    r_scu = req_scu and acc_scu
    r_scp = req_scp and acc_scp
    a_scu = r_scp
    a_scp = r_scu
    return (r_scu, r_scp, a_scu, a_scp)


# ---------------------------------------------------------------------------
# FRAGMENTATION
# ---------------------------------------------------------------------------

def fragment_pdata(pdvs, max_pdu_length):
    """Pack PDV items into P-DATA-TF PDUs respecting max_pdu_length."""
    results = []
    for pdv in pdvs:
        cid = pdv['context_id']
        is_cmd = pdv['is_command']
        data = pdv['data']

        if max_pdu_length == 0:
            results.append(encode_pdu({
                'pdu_type': 0x04,
                'pdvs': [{'context_id': cid, 'is_command': is_cmd,
                          'is_last': pdv['is_last'], 'data': data}]
            }))
        else:
            max_data = max_pdu_length - 12
            if max_data <= 0:
                raise ValueError("max_pdu_length too small")
            if len(data) <= max_data:
                results.append(encode_pdu({
                    'pdu_type': 0x04,
                    'pdvs': [{'context_id': cid, 'is_command': is_cmd,
                              'is_last': pdv['is_last'], 'data': data}]
                }))
            else:
                offset = 0
                while offset < len(data):
                    chunk = data[offset:offset + max_data]
                    is_final = (offset + max_data >= len(data))
                    results.append(encode_pdu({
                        'pdu_type': 0x04,
                        'pdvs': [{'context_id': cid, 'is_command': is_cmd,
                                  'is_last': pdv['is_last'] if is_final else False,
                                  'data': chunk}]
                    }))
                    offset += max_data
    return results


# ---------------------------------------------------------------------------
# STREAM ANALYSIS
# ---------------------------------------------------------------------------

def analyze_stream(filepath):
    """Read a capture file (raw, timestamped, or PCAP) and return analysis."""
    with open(filepath, 'rb') as f:
        data = f.read()

    # PCAP format detection by magic bytes
    if len(data) >= 4 and data[:4] in (b'\xa1\xb2\xc3\xd4', b'\xd4\xc3\xb2\xa1'):
        return _analyze_pcap(filepath)

    framing = _detect_framing(data)
    pdus = []
    violation_summary = {'NONZERO_RESERVED': 0, 'UID_TOO_LONG': 0}
    pos = 0

    while pos < len(data):
        timestamp = None
        if framing == 'timestamped':
            ts_sec = struct.unpack('>I', data[pos:pos + 4])[0]
            pdu_size = struct.unpack('>I', data[pos + 4:pos + 8])[0]
            timestamp = float(ts_sec)
            pdu_offset = pos + 8
            pdu_bytes = data[pdu_offset:pdu_offset + pdu_size]
            next_pos = pdu_offset + pdu_size
        else:
            pdu_offset = pos
            pdu_len = struct.unpack('>I', data[pos + 2:pos + 6])[0]
            pdu_size = 6 + pdu_len
            pdu_bytes = data[pos:pos + pdu_size]
            next_pos = pos + pdu_size

        pdu_type_val = pdu_bytes[0]
        pdu_length = struct.unpack('>I', pdu_bytes[2:6])[0]

        violations = []
        if pdu_bytes[1] != 0:
            violations.append('NONZERO_RESERVED')
            violation_summary['NONZERO_RESERVED'] += 1

        decoded = decode_pdu(pdu_bytes)
        _check_uid_lengths(decoded, violations, violation_summary)

        pdus.append({
            'offset': pdu_offset,
            'pdu_type': pdu_type_val,
            'pdu_type_name': PDU_TYPE_NAMES.get(pdu_type_val,
                                                 f'UNKNOWN-0x{pdu_type_val:02x}'),
            'length': pdu_length,
            'timestamp': timestamp,
            'violations': violations,
            'decoded': decoded,
        })
        pos = next_pos

    return {
        'framing': framing,
        'pdu_count': len(pdus),
        'pdus': pdus,
        'violation_summary': violation_summary,
    }


def _analyze_pcap(filepath):
    """Extract DICOM PDUs from a PCAP file using tshark for TCP reassembly."""
    proc = subprocess.run(
        ['tshark', '-r', filepath, '-q', '-z', 'follow,tcp,raw,0'],
        capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tshark failed: {proc.stderr.strip()}")

    raw_bytes = b''
    for line in proc.stdout.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('=') or stripped.startswith('Follow:') or \
           stripped.startswith('Filter:') or stripped.startswith('Node'):
            continue
        try:
            raw_bytes += bytes.fromhex(stripped)
        except ValueError:
            continue

    pdus = []
    violation_summary = {'NONZERO_RESERVED': 0, 'UID_TOO_LONG': 0}
    pos = 0

    while pos < len(raw_bytes):
        if pos + 6 > len(raw_bytes):
            break
        pdu_len = struct.unpack('>I', raw_bytes[pos + 2:pos + 6])[0]
        pdu_size = 6 + pdu_len
        pdu_bytes = raw_bytes[pos:pos + pdu_size]

        pdu_type_val = pdu_bytes[0]
        violations = []
        if pdu_bytes[1] != 0:
            violations.append('NONZERO_RESERVED')
            violation_summary['NONZERO_RESERVED'] += 1

        decoded = decode_pdu(pdu_bytes)
        _check_uid_lengths(decoded, violations, violation_summary)

        pdus.append({
            'offset': pos,
            'pdu_type': pdu_type_val,
            'pdu_type_name': PDU_TYPE_NAMES.get(pdu_type_val,
                                                 f'UNKNOWN-0x{pdu_type_val:02x}'),
            'length': pdu_len,
            'timestamp': None,
            'violations': violations,
            'decoded': decoded,
        })
        pos += pdu_size

    return {
        'framing': 'pcap',
        'pdu_count': len(pdus),
        'pdus': pdus,
        'violation_summary': violation_summary,
    }


def _detect_framing(data):
    if len(data) == 0:
        return 'raw'
    first_byte = data[0]
    if first_byte in PDU_TYPE_NAMES:
        return 'raw'
    if len(data) >= 14:
        pdu_size = struct.unpack('>I', data[4:8])[0]
        if pdu_size >= 6 and len(data) >= 8 + pdu_size:
            pdu_type = data[8]
            if pdu_type in PDU_TYPE_NAMES:
                return 'timestamped'
    return 'raw'


def _check_uid_lengths(decoded, violations, summary):
    def _chk(uid_str):
        if uid_str and len(uid_str) > 64:
            violations.append('UID_TOO_LONG')
            summary['UID_TOO_LONG'] += 1

    if 'application_context' in decoded:
        _chk(decoded.get('application_context'))
    if 'user_info' in decoded:
        ui = decoded['user_info']
        _chk(ui.get('implementation_class_uid'))
    if 'presentation_contexts' in decoded:
        for pc in decoded['presentation_contexts']:
            _chk(pc.get('abstract_syntax'))
            for ts in pc.get('transfer_syntaxes', []):
                _chk(ts)
            _chk(pc.get('transfer_syntax'))


class _BytesEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return list(obj)
        return super().default(obj)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <capture_file>", file=sys.stderr)
        sys.exit(1)
    result = analyze_stream(sys.argv[1])
    print(json.dumps(result, cls=_BytesEncoder, indent=2))

"""DICOM Upper Layer PDU Codec — partial implementation.

This codec handles decoding and encoding of DICOM Upper Layer Protocol
Data Units per PS3.8 Section 9.3. Some functions are not yet implemented.
"""

import struct
import json
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
            max_pdu = struct.unpack('<I', sd)[0]
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
        is_command = bool(mch & 0x02)
        is_last = bool(mch & 0x01)
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
    return struct.pack('>BxH', 0x20, len(body)) + body


def _encode_user_info(ui):
    sub = b''
    sub += struct.pack('>BxHI', 0x51, 4, ui['max_pdu_length'])
    ic = ui['implementation_class_uid'].encode('ascii')
    sub += struct.pack('>BxH', 0x52, len(ic)) + ic
    if ui['implementation_version_name'] is not None:
        iv = ui['implementation_version_name'].encode('ascii')
        sub += struct.pack('>BxH', 0x52, len(iv)) + iv
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
# ROLE NEGOTIATION (not yet implemented)
# ---------------------------------------------------------------------------

def negotiate_roles(req_scu, req_scp, acc_scu, acc_scp):
    raise NotImplementedError("negotiate_roles not yet implemented")


# ---------------------------------------------------------------------------
# FRAGMENTATION (not yet implemented)
# ---------------------------------------------------------------------------

def fragment_pdata(pdvs, max_pdu_length):
    raise NotImplementedError("fragment_pdata not yet implemented")


# ---------------------------------------------------------------------------
# STREAM ANALYSIS (not yet implemented)
# ---------------------------------------------------------------------------

def analyze_stream(filepath):
    raise NotImplementedError("analyze_stream not yet implemented")

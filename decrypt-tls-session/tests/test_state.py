
"""
Verification tests for TLS 1.3 forensic analysis task.

These tests independently re-derive the correct answers by performing the
same TLS 1.3 key schedule on the actual captures and leaked keys. No
ground-truth is stored anywhere in the Docker image — all expected values
are computed at test time from the cryptographic material.
"""

import hashlib
import hmac as hmac_mod
import json
import os
import struct
import glob as glob_mod

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DATA_DIR = '/opt/tls_forensics'
CAPTURES_DIR = f'{DATA_DIR}/captures'


# ================================================================
# TLS 1.3 key derivation (duplicated here so tests are self-contained
# and don't depend on any solution code)
# ================================================================

def _hmac_sha256(key, data):
    return hmac_mod.new(key, data, hashlib.sha256).digest()


def _hkdf_extract(salt, ikm):
    return _hmac_sha256(salt, ikm)


def _hkdf_expand(prk, info, length):
    n = (length + 31) // 32
    okm, t = b'', b''
    for i in range(1, n + 1):
        t = _hmac_sha256(prk, t + info + bytes([i]))
        okm += t
    return okm[:length]


def _hkdf_expand_label(secret, label, context, length):
    lb = b'tls13 ' + (label.encode() if isinstance(label, str) else label)
    hl = struct.pack('!H', length)
    hl += struct.pack('!B', len(lb)) + lb
    hl += struct.pack('!B', len(context)) + context
    return _hkdf_expand(secret, hl, length)


def _derive_secret(secret, label, messages):
    return _hkdf_expand_label(secret, label, hashlib.sha256(messages).digest(), 32)


def _parse_server_hello_pubkey(sh_msg):
    offset = 4 + 2 + 32
    sid_len = sh_msg[offset]
    offset += 1 + sid_len + 2 + 1
    ext_total = struct.unpack('!H', sh_msg[offset:offset+2])[0]
    offset += 2
    ext_end = offset + ext_total
    while offset < ext_end:
        et = struct.unpack('!H', sh_msg[offset:offset+2])[0]
        edl = struct.unpack('!H', sh_msg[offset+2:offset+4])[0]
        ed = sh_msg[offset+4:offset+4+edl]
        if et == 0x0033:
            kl = struct.unpack('!H', ed[2:4])[0]
            return ed[4:4+kl]
        offset += 4 + edl
    raise ValueError("key_share not found")


def _extract_session_id(hs_msg):
    offset = 4 + 2 + 32
    sid_len = hs_msg[offset]
    return hs_msg[offset+1:offset+1+sid_len]


# ================================================================
# Fixture: compute the ground truth from captures + keys
# ================================================================

@pytest.fixture(scope='session')
def ground_truth():
    """Independently derive all expected answers from cryptographic material."""

    # Load all records
    records = {}
    for fp in sorted(glob_mod.glob(f'{CAPTURES_DIR}/record_*.bin')):
        fn = os.path.basename(fp)
        with open(fp, 'rb') as f:
            records[fn] = f.read()

    # Classify records
    plaintext_hs = {}
    encrypted = {}
    for fn, data in records.items():
        if data[0] == 0x16:
            plaintext_hs[fn] = data[5:]
        elif data[0] == 0x17:
            encrypted[fn] = data

    # Match ClientHello/ServerHello by session_id
    client_hellos, server_hellos = {}, {}
    for fn, hs_data in plaintext_hs.items():
        sid = _extract_session_id(hs_data)
        if hs_data[0] == 0x01:
            client_hellos[sid] = (fn, hs_data)
        elif hs_data[0] == 0x02:
            server_hellos[sid] = (fn, hs_data)

    sessions = {}
    for sid in client_hellos:
        if sid in server_hellos:
            sessions[sid] = {
                'ch_fn': client_hellos[sid][0],
                'ch_hs': client_hellos[sid][1],
                'sh_fn': server_hellos[sid][0],
                'sh_hs': server_hellos[sid][1],
            }

    # Read keys
    keys = {}
    with open(f'{DATA_DIR}/leaked_key_alpha.hex') as f:
        keys['alpha'] = bytes.fromhex(f.read().strip())
    with open(f'{DATA_DIR}/leaked_key_beta.hex') as f:
        keys['beta'] = bytes.fromhex(f.read().strip())

    # Try all (session, key) combos to find the intact session
    result = None
    z32 = b'\x00' * 32

    for sid, sess in sessions.items():
        if result:
            break
        for kname, kbytes in keys.items():
            if result:
                break
            spub = _parse_server_hello_pubkey(sess['sh_hs'])
            ckey = X25519PrivateKey.from_private_bytes(kbytes)
            spub_key = X25519PublicKey.from_public_bytes(spub)
            shared = ckey.exchange(spub_key)

            es = _hkdf_extract(z32, z32)
            d1 = _derive_secret(es, "derived", b"")
            hs_secret = _hkdf_extract(d1, shared)
            transcript = sess['ch_hs'] + sess['sh_hs']
            s_hs_ts = _derive_secret(hs_secret, "s hs traffic", transcript)
            s_hs_key = _hkdf_expand_label(s_hs_ts, "key", b"", 16)
            s_hs_iv = _hkdf_expand_label(s_hs_ts, "iv", b"", 12)
            aesgcm = AESGCM(s_hs_key)

            for efn, edata in encrypted.items():
                aad, ct = edata[:5], edata[5:]
                try:
                    pt = aesgcm.decrypt(s_hs_iv, ct, aad)
                except Exception:
                    continue
                hs_content = pt[:-1]

                # Derive app keys
                tf = transcript + hs_content
                d2 = _derive_secret(hs_secret, "derived", b"")
                ms = _hkdf_extract(d2, z32)
                s_app_ts = _derive_secret(ms, "s ap traffic", tf)
                s_app_key = _hkdf_expand_label(s_app_ts, "key", b"", 16)
                s_app_iv = _hkdf_expand_label(s_app_ts, "iv", b"", 12)
                aesgcm_app = AESGCM(s_app_key)

                for afn, adata in encrypted.items():
                    if afn == efn:
                        continue
                    aad_a, ct_a = adata[:5], adata[5:]
                    try:
                        pt_a = aesgcm_app.decrypt(s_app_iv, ct_a, aad_a)
                    except Exception:
                        continue
                    result = {
                        'intact_key': kname,
                        'compromised_key': 'beta' if kname == 'alpha' else 'alpha',
                        'session_sid': sid,
                        'session': sess,
                        'hs_fn': efn,
                        'app_fn': afn,
                        'app_plaintext': pt_a[:-1],
                    }
                    break
                if result:
                    break

    assert result is not None, "Test setup: could not decrypt any session"

    intact_records = sorted([
        result['session']['ch_fn'],
        result['session']['sh_fn'],
        result['hs_fn'],
        result['app_fn'],
    ])
    all_fns = set(records.keys())
    compromised_records = sorted(list(all_fns - set(intact_records)))

    # Identify tampered record: the compromised session's encrypted record
    # that is a handshake (smaller) vs application data (larger)
    comp_enc = []
    for fn in compromised_records:
        if records[fn][0] == 0x17:
            comp_enc.append((fn, len(records[fn])))
    comp_enc.sort(key=lambda x: x[1])
    tampered_fn = comp_enc[0][0]

    return {
        'intact_session': result['intact_key'],
        'compromised_session': result['compromised_key'],
        'tampered_record': tampered_fn,
        'intact_records': intact_records,
        'compromised_records': compromised_records,
        'app_plaintext': result['app_plaintext'],
    }


def load_report():
    with open('/app/forensic_report.json') as f:
        return json.load(f)


# ================================================================
# Tests
# ================================================================

class TestPlaintext:
    def test_output_exists(self):
        """Decrypted plaintext file must exist."""
        assert os.path.exists('/app/plaintext.txt'), \
            "/app/plaintext.txt not found"

    def test_output_matches(self, ground_truth):
        """Decrypted content must match independently-derived plaintext."""
        with open('/app/plaintext.txt', 'rb') as f:
            actual = f.read()
        expected = ground_truth['app_plaintext']
        assert hashlib.sha256(actual).hexdigest() == hashlib.sha256(expected).hexdigest(), \
            "Decrypted plaintext does not match — key derivation or decryption error"


class TestForensicReport:
    def test_report_exists(self):
        """Forensic report file must exist."""
        assert os.path.exists('/app/forensic_report.json'), \
            "/app/forensic_report.json not found"

    def test_report_valid_json(self):
        """Forensic report must be valid JSON with required fields."""
        report = load_report()
        assert isinstance(report, dict)
        for field in ['intact_session', 'compromised_session',
                      'tampered_record', 'session_records',
                      'vulnerability_assessment']:
            assert field in report, f"Missing required field: {field}"

    def test_intact_session(self, ground_truth):
        """Must correctly identify which session was intact."""
        report = load_report()
        assert report['intact_session'] == ground_truth['intact_session'], \
            f"Expected intact session '{ground_truth['intact_session']}'"

    def test_compromised_session(self, ground_truth):
        """Must correctly identify which session was compromised."""
        report = load_report()
        assert report['compromised_session'] == ground_truth['compromised_session'], \
            f"Expected compromised session '{ground_truth['compromised_session']}'"

    def test_tampered_record(self, ground_truth):
        """Must pinpoint the specific tampered record."""
        report = load_report()
        assert report['tampered_record'] == ground_truth['tampered_record'], \
            f"Expected tampered record '{ground_truth['tampered_record']}'"

    def test_session_records_intact(self, ground_truth):
        """Intact session record assignments must be correct."""
        report = load_report()
        intact = ground_truth['intact_session']
        actual = sorted(report['session_records'][intact])
        assert actual == ground_truth['intact_records'], \
            f"Intact session records mismatch"

    def test_session_records_compromised(self, ground_truth):
        """Compromised session record assignments must be correct."""
        report = load_report()
        comp = ground_truth['compromised_session']
        actual = sorted(report['session_records'][comp])
        assert actual == ground_truth['compromised_records'], \
            f"Compromised session records mismatch"

    def test_vulnerability_assessment(self):
        """Vulnerability assessment must be a substantive explanation."""
        report = load_report()
        assessment = report.get('vulnerability_assessment', '')
        assert isinstance(assessment, str) and len(assessment) > 50, \
            "vulnerability_assessment must be a substantive string (>50 chars)"

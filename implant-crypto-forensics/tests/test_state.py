
import base64
import hashlib
import json
import os
import sqlite3
import struct
import subprocess
import pytest


# ============================================================
# Shared cipher utilities (for computational verification)
# ============================================================

PHI = 0x9E3779B9


def ksa(key):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    return S


def compute_inv(S):
    inv = [0] * 256
    for i in range(256):
        inv[S[i]] = i
    return inv


def decrypt_se(ct, key, tweak, max_bytes=None):
    """Decrypt using the stream engine (inverse of se_transform)."""
    S = ksa(key)
    inv_S = compute_inv(S)
    n = len(ct) if max_bytes is None else min(max_bytes, len(ct))
    pt = bytearray()
    for i in range(n):
        tb = tweak[i % len(tweak)]
        pb = ((i + 1) * PHI) & 0xFF
        sb = ct[i] ^ tb ^ pb
        pt.append(inv_S[sb])
        if (i + 1) % 256 == 0:
            fb = ct[max(0, i + 1 - 16): i + 1]
            j = 0
            for k in range(256):
                j = (j + S[k] + fb[k % len(fb)]) % 256
                S[k], S[j] = S[j], S[k]
            inv_S = compute_inv(S)
    return bytes(pt)


def derive_se_key(db_data, auth_token_bytes):
    """Re-derive the stream engine key from DB fragments and auth token."""
    node_id = db_data["config"]["node_id"].encode("utf-8")
    node_id_md5 = hashlib.md5(node_id).digest()[:8]
    primary = bytes.fromhex(db_data["fragments"]["primary"])
    secondary = base64.b64decode(db_data["fragments"]["secondary"])
    kp1 = bytes(a ^ b for a, b in zip(primary, auth_token_bytes[:8]))
    kp2 = bytes(a ^ b for a, b in zip(secondary, node_id_md5))
    return kp1 + kp2


def derive_tweak(session_id):
    return hashlib.sha256(session_id.encode("utf-8")).digest()[:8]


def load_db():
    """Load all relevant data from the implant database."""
    db = sqlite3.connect("/app/implant.db")
    db.row_factory = sqlite3.Row
    config = {}
    for row in db.execute("SELECT key, value FROM config"):
        config[row["key"]] = row["value"]
    fragments = {}
    for row in db.execute("SELECT fragment_type, fragment_data FROM key_fragments"):
        fragments[row["fragment_type"]] = row["fragment_data"]
    sessions = []
    for row in db.execute("SELECT * FROM sessions"):
        sessions.append({k: row[k] for k in row.keys()})
    db.close()
    active = next(s for s in sessions if s["status"] == "active")
    return {
        "config": config,
        "fragments": fragments,
        "sessions": sessions,
        "active_session": active,
    }


def reassemble_from_pcap():
    """Parse the pcap to extract and reorder exfil chunks by sequence number."""
    exfil_chunks = []
    with open("/app/exfil_traffic.pcap", "rb") as f:
        f.read(24)  # global header
        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', phdr)
            pkt = f.read(incl_len)
            if len(pkt) < incl_len:
                break
            if len(pkt) < 42:
                continue
            ethertype = struct.unpack('>H', pkt[12:14])[0]
            if ethertype != 0x0800:
                continue
            protocol = pkt[23]
            if protocol != 17:
                continue
            ip_ihl = (pkt[14] & 0x0F) * 4
            udp_off = 14 + ip_ihl
            if len(pkt) < udp_off + 8:
                continue
            dst_port = struct.unpack('>H', pkt[udp_off + 2: udp_off + 4])[0]
            if dst_port != 8443:
                continue
            payload = pkt[udp_off + 8:]
            if len(payload) < 8:
                continue
            magic = struct.unpack('>I', payload[:4])[0]
            if magic != 0xC0DE0001:
                continue
            seq = struct.unpack('>I', payload[4:8])[0]
            data = payload[8:]
            exfil_chunks.append((seq, data))
    exfil_chunks.sort(key=lambda x: x[0])
    ciphertext = b''.join(d for _, d in exfil_chunks)
    return ciphertext, exfil_chunks


def load_analysis():
    with open("/app/analysis.json") as f:
        return json.load(f)


# ============================================================
# Tests: Analysis Report (verified by computation)
# ============================================================


class TestAnalysisReport:
    """Verify the forensic analysis by computational re-derivation."""

    def test_analysis_file_exists(self):
        assert os.path.isfile("/app/analysis.json"), \
            "/app/analysis.json not found"

    def test_analysis_is_valid_json(self):
        with open("/app/analysis.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "analysis.json must be a JSON object"

    def test_cipher_engine_verified_by_decryption(self):
        """Verify the claimed cipher engine produces valid decryption."""
        analysis = load_analysis()
        engine = analysis.get("cipher_engine", "").lower().strip()
        assert engine in ["se", "stream", "stream_engine", "se_transform"], \
            f"Unexpected cipher engine: {engine}"

        ciphertext, _ = reassemble_from_pcap()
        db_data = load_db()
        token = bytes.fromhex(analysis["recovered_auth_token"])
        key = derive_se_key(db_data, token)
        tweak = derive_tweak(db_data["active_session"]["session_id"])
        header = decrypt_se(ciphertext, key, tweak, max_bytes=16)
        assert header == b"CLASSIFICATION: ", \
            "Decryption with claimed parameters does not produce expected header"

    def test_recovered_auth_token_full_decryption(self):
        """Full decryption with recovered token yields a structurally valid document."""
        analysis = load_analysis()
        ciphertext, _ = reassemble_from_pcap()
        db_data = load_db()
        token = bytes.fromhex(analysis["recovered_auth_token"])
        key = derive_se_key(db_data, token)
        tweak = derive_tweak(db_data["active_session"]["session_id"])
        plaintext = decrypt_se(ciphertext, key, tweak)
        assert plaintext.startswith(b"CLASSIFICATION:")
        assert b"DOCUMENT-ID:" in plaintext
        assert b"SIGMA-7-ECHO-TANGO-4921-FOXTROT" in plaintext

    def test_corrupted_positions_consistent_with_db(self):
        """Claimed corrupted positions match where stored and recovered tokens differ."""
        analysis = load_analysis()
        db_data = load_db()
        stored = bytes.fromhex(db_data["active_session"]["auth_token"])
        recovered = bytes.fromhex(analysis["recovered_auth_token"])
        claimed = sorted(analysis.get("corrupted_byte_positions", []))
        actual_diff = sorted(
            i for i in range(min(len(stored), len(recovered)))
            if stored[i] != recovered[i]
        )
        assert claimed == actual_diff, \
            f"Claimed positions {claimed} != actual differences {actual_diff}"


# ============================================================
# Tests: Vulnerability Evaluation
# ============================================================


class TestVulnerabilityEvaluation:
    """Verify the solver correctly evaluated both engines' security."""

    def test_weaker_engine_evaluation(self):
        """RE uses repeating-key XOR — trivially broken with known plaintext."""
        analysis = load_analysis()
        weaker = analysis.get("weaker_engine", "").lower().strip()
        assert weaker in ["re", "recovery", "re_transform", "recovery_engine"], \
            f"Incorrect weaker_engine assessment: '{weaker}'"

    def test_kpa_bytes_evaluation(self):
        """RE key is 16 bytes; 16 consecutive known-plaintext bytes fully recover it."""
        analysis = load_analysis()
        kpa = analysis.get("kpa_bytes_for_full_key_recovery")
        assert isinstance(kpa, int), \
            f"kpa_bytes_for_full_key_recovery must be an integer, got {type(kpa)}"
        assert kpa == 16, \
            f"Incorrect KPA byte count: {kpa}, expected 16"


# ============================================================
# Tests: Exfiltration Detector
# ============================================================


class TestExfilDetector:
    """Verify the solver created a working exfiltration detection tool."""

    def test_detector_exists(self):
        assert os.path.isfile("/app/exfil_detector.py"), \
            "/app/exfil_detector.py not found"

    def test_detector_runs_successfully(self):
        result = subprocess.run(
            ["python3", "/app/exfil_detector.py", "/app/exfil_traffic.pcap"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Detector exited with code {result.returncode}: {result.stderr}"

    def test_detector_outputs_valid_json(self):
        result = subprocess.run(
            ["python3", "/app/exfil_detector.py", "/app/exfil_traffic.pcap"],
            capture_output=True, text=True, timeout=30
        )
        output = json.loads(result.stdout.strip())
        assert "exfil_packet_count" in output
        assert "sequence_numbers" in output
        assert "total_payload_bytes" in output

    def test_detector_correct_packet_count(self):
        """Detector must find exactly the exfil packets, not keepalive probes."""
        result = subprocess.run(
            ["python3", "/app/exfil_detector.py", "/app/exfil_traffic.pcap"],
            capture_output=True, text=True, timeout=30
        )
        output = json.loads(result.stdout.strip())
        _, chunks = reassemble_from_pcap()
        expected_count = len(chunks)
        assert output["exfil_packet_count"] == expected_count, \
            f"Expected {expected_count} exfil packets, got {output['exfil_packet_count']}"

    def test_detector_correct_sequence_numbers(self):
        result = subprocess.run(
            ["python3", "/app/exfil_detector.py", "/app/exfil_traffic.pcap"],
            capture_output=True, text=True, timeout=30
        )
        output = json.loads(result.stdout.strip())
        _, chunks = reassemble_from_pcap()
        expected_seqs = sorted(seq for seq, _ in chunks)
        assert sorted(output["sequence_numbers"]) == expected_seqs, \
            f"Sequence mismatch"

    def test_detector_correct_payload_bytes(self):
        result = subprocess.run(
            ["python3", "/app/exfil_detector.py", "/app/exfil_traffic.pcap"],
            capture_output=True, text=True, timeout=30
        )
        output = json.loads(result.stdout.strip())
        _, chunks = reassemble_from_pcap()
        expected_bytes = sum(len(d) for _, d in chunks)
        assert output["total_payload_bytes"] == expected_bytes, \
            f"Expected {expected_bytes} payload bytes, got {output['total_payload_bytes']}"


# ============================================================
# Tests: Decryption Output
# ============================================================


class TestDecryptionOutput:
    """Verify the decrypted document by re-computing decryption."""

    def test_answer_file_exists(self):
        assert os.path.isfile("/app/answer.txt"), "/app/answer.txt not found"

    def test_decrypted_doc_exists(self):
        assert os.path.isfile("/app/decrypted_doc.txt"), \
            "/app/decrypted_doc.txt not found"

    def test_decrypted_doc_verified_by_recomputation(self):
        """Re-decrypt with claimed parameters and compare to solver's output."""
        analysis = load_analysis()
        ciphertext, _ = reassemble_from_pcap()
        db_data = load_db()
        token = bytes.fromhex(analysis["recovered_auth_token"])
        key = derive_se_key(db_data, token)
        tweak = derive_tweak(db_data["active_session"]["session_id"])
        expected_pt = decrypt_se(ciphertext, key, tweak)

        with open("/app/decrypted_doc.txt", "rb") as f:
            actual_pt = f.read()
        assert actual_pt == expected_pt, \
            "decrypted_doc.txt does not match recomputed decryption"

    def test_answer_matches_doc_hash(self):
        """answer.txt must be the SHA-256 of decrypted_doc.txt."""
        with open("/app/answer.txt") as f:
            answer = f.read().strip()
        with open("/app/decrypted_doc.txt", "rb") as f:
            content = f.read()
        computed = hashlib.sha256(content).hexdigest()
        assert answer == computed, \
            f"answer.txt ({answer[:16]}...) != SHA-256 of doc ({computed[:16]}...)"

    def test_decrypted_doc_starts_with_classification(self):
        with open("/app/decrypted_doc.txt", "rb") as f:
            content = f.read()
        assert content.startswith(b"CLASSIFICATION:"), \
            "Decrypted document does not begin with expected header"

    def test_decrypted_doc_contains_document_id(self):
        with open("/app/decrypted_doc.txt", "rb") as f:
            content = f.read()
        assert b"DOCUMENT-ID:" in content, \
            "Decrypted document missing DOCUMENT-ID marker"

    def test_decrypted_doc_contains_authentication(self):
        with open("/app/decrypted_doc.txt", "rb") as f:
            content = f.read()
        assert b"SIGMA-7-ECHO-TANGO-4921-FOXTROT" in content, \
            "Decrypted document missing authentication code"

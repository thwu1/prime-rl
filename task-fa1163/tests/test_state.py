
"""
Tests for VoiceLink signaling server security audit & hardening.

Verifies:
  1. The original server contains 4 known state machine vulnerabilities.
  2. The agent created exploit scripts, pcap captures, and findings.
  3. The agent's exploit scripts succeed against the original server.
  4. The pcap captures are valid and contain VLSP traffic.
  5. The findings include valid CVSS 3.1 assessments.
  6. The hardened server passes the conformance test suite.
  7. The hardened server rejects all 4 exploit patterns.
"""

import json
import os
import re
import socket
import struct
import subprocess
import sys
import time

import pytest

sys.path.insert(0, '/app/voicelink')
from protocol import (HEADER_SIZE, MAGIC, VERSION, MsgType,
                      encode, decode, make_id)

SERVER_HOST = '127.0.0.1'
ORIGINAL_PORT = 9877
HARDENED_PORT = 9878


# ---------------------------------------------------------------------------
# Helper: minimal VLSP client with retry
# ---------------------------------------------------------------------------

def _wait_for_port(port, timeout=15):
    """Block until a TCP port accepts connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((SERVER_HOST, port))
            s.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.5)
    return False


class VLSPClient:
    def __init__(self, port=ORIGINAL_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(15)
        self.sock.connect((SERVER_HOST, port))

    def _recv_raw(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def transact(self, msg_type, session_id, sender_id, fields):
        self.sock.sendall(encode(msg_type, session_id, sender_id, fields))
        hdr = self._recv_raw(HEADER_SIZE)
        _, _, _, total_len = struct.unpack_from('!4sHHI', hdr)
        body = self._recv_raw(total_len - HEADER_SIZE) if total_len > HEADER_SIZE else b''
        return decode(hdr + body)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def _callee_media_status(client, session_id, sender_id):
    """Query session and return (callee_transmitting, callee_consent)."""
    _, _, _, resp = client.transact(MsgType.STATUS, session_id, sender_id, {})
    st = json.loads(resp.get('session_status', '{}'))
    c = st.get('callee', {})
    tx = (c.get('audio', {}).get('transmitting', False)
          or c.get('video', {}).get('transmitting', False))
    consent = c.get('consent_given', True)
    return tx, consent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def original_server():
    """Ensure original server is running on ORIGINAL_PORT."""
    if _wait_for_port(ORIGINAL_PORT, timeout=3):
        yield None
        return

    proc = subprocess.Popen(
        [sys.executable, '/app/voicelink/server.py'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait_for_port(ORIGINAL_PORT, timeout=10), \
        "Original server failed to start on port 9877"
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope='module')
def hardened_server():
    """Ensure hardened server is running on HARDENED_PORT."""
    path = '/app/voicelink/server_hardened.py'
    if not os.path.isfile(path):
        pytest.skip("server_hardened.py not found")

    if _wait_for_port(HARDENED_PORT, timeout=3):
        yield None
        return

    env = os.environ.copy()
    env['VLSP_PORT'] = str(HARDENED_PORT)
    proc = subprocess.Popen(
        [sys.executable, path], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait_for_port(HARDENED_PORT, timeout=10), \
        "Hardened server failed to start on port 9878"
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ===================================================================
# Reference exploit tests — verify the original server has each vuln
# ===================================================================

class TestServerVulnerabilities:
    """Reference exploits proving the 4 vulnerabilities exist in the original server."""

    def test_vuln_connect_spoofing(self, original_server):
        """CONNECT accepted from caller (should require callee)."""
        c = VLSPClient(ORIGINAL_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller, {'display_name': 'a'})
            c.transact(MsgType.REGISTER, z, callee, {'display_name': 'b'})
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
            _, _, _, resp = c.transact(MsgType.CONNECT, sid, caller, {})
            assert resp.get('status') == 'ok', f"CONNECT should succeed: {resp}"
            tx, _ = _callee_media_status(c, sid, caller)
            assert tx, "Callee media must be transmitting"
        finally:
            c.close()

    def test_vuln_embedded_candidates(self, original_server):
        """Inline ICE candidates in OFFER cause premature connection."""
        c = VLSPClient(ORIGINAL_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller, {'display_name': 'a'})
            c.transact(MsgType.REGISTER, z, callee, {'display_name': 'b'})
            sdp = ('v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'
                   'a=candidate:1 1 udp 2130706431 10.0.0.1 50000 typ host\r\n')
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': sdp})
            tx, _ = _callee_media_status(c, sid, caller)
            assert tx, "Callee media must be transmitting"
        finally:
            c.close()

    def test_vuln_sdp_update_ringing(self, original_server):
        """SDP_UPDATE triggers media for multi-device callee in RINGING."""
        c = VLSPClient(ORIGINAL_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller,
                       {'display_name': 'a', 'device_count': 1})
            c.transact(MsgType.REGISTER, z, callee,
                       {'display_name': 'b', 'device_count': 2})
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
            c.transact(MsgType.CANDIDATE, sid, caller,
                       {'candidate': 'candidate:1 1 udp 2130706431 10.0.0.1 5000 typ host'})
            c.transact(MsgType.SDP_UPDATE, sid, caller,
                       {'sdp': 'v=0\r\n', 'reason': 'add_video'})
            tx, _ = _callee_media_status(c, sid, caller)
            assert tx, "Callee media must be transmitting"
        finally:
            c.close()

    def test_vuln_type_confusion(self, original_server):
        """String media_policy bypasses consent via truthiness check."""
        c = VLSPClient(ORIGINAL_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller, {'display_name': 'a'})
            c.transact(MsgType.REGISTER, z, callee, {'display_name': 'b'})
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
            c.transact(MsgType.MEDIA_CONFIG, sid, caller,
                       {'media_policy': 'auto_enable'})
            tx, _ = _callee_media_status(c, sid, caller)
            assert tx, "Callee media must be transmitting"
        finally:
            c.close()


# ===================================================================
# Agent output tests — verify the agent created required artifacts
# ===================================================================

class TestAgentOutput:
    """Verify the agent created correct exploits, captures, and findings."""

    def test_exploit_files_exist(self):
        d = '/app/exploits'
        assert os.path.isdir(d), "No /app/exploits directory"
        files = [f for f in os.listdir(d)
                 if f.startswith('exploit_') and f.endswith('.py')]
        assert len(files) >= 4, f"Expected >=4 exploit scripts, found {len(files)}: {files}"

    def test_findings_files_exist(self):
        d = '/app/exploits/findings'
        assert os.path.isdir(d), "No /app/exploits/findings directory"
        files = [f for f in os.listdir(d) if f.endswith('.json')]
        assert len(files) >= 4, f"Expected >=4 findings, found {len(files)}: {files}"

    def test_findings_format(self):
        d = '/app/exploits/findings'
        if not os.path.isdir(d):
            pytest.skip("No findings directory")
        required = {'vulnerability_name', 'description', 'root_cause',
                     'impact', 'callee_media_transmitted'}
        for fname in os.listdir(d):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(d, fname)
            with open(path) as fh:
                data = json.load(fh)
            missing = required - set(data.keys())
            assert not missing, f"{fname} missing: {missing}"
            assert data['callee_media_transmitted'] is True, \
                f"{fname}: callee_media_transmitted must be true"

    def test_findings_distinct(self):
        d = '/app/exploits/findings'
        if not os.path.isdir(d):
            pytest.skip("No findings directory")
        names = set()
        for fname in os.listdir(d):
            if not fname.endswith('.json'):
                continue
            with open(os.path.join(d, fname)) as fh:
                data = json.load(fh)
            names.add(data['vulnerability_name'])
        assert len(names) >= 4, f"Expected >=4 distinct vulns, got: {names}"

    def test_agent_exploits_run(self, original_server):
        d = '/app/exploits'
        if not os.path.isdir(d):
            pytest.skip("No exploits directory")
        scripts = sorted(f for f in os.listdir(d)
                         if f.startswith('exploit_') and f.endswith('.py'))
        assert len(scripts) >= 4
        for s in scripts:
            r = subprocess.run(
                [sys.executable, os.path.join(d, s)],
                capture_output=True, text=True, timeout=30, cwd='/app')
            assert r.returncode == 0, \
                f"{s} failed (rc={r.returncode}):\nstdout: {r.stdout}\nstderr: {r.stderr}"

    def test_hardened_server_exists(self):
        assert os.path.isfile('/app/voicelink/server_hardened.py'), \
            "Hardened server not found at /app/voicelink/server_hardened.py"


# ===================================================================
# Traffic capture tests — verify pcap files are valid
# ===================================================================

class TestTrafficCaptures:
    """Verify pcap capture files exist and contain VLSP traffic."""

    def test_capture_files_exist(self):
        d = '/app/captures'
        assert os.path.isdir(d), "No /app/captures directory"
        pcaps = [f for f in os.listdir(d) if f.endswith('.pcap')]
        assert len(pcaps) >= 4, \
            f"Expected >=4 pcap files, found {len(pcaps)}: {pcaps}"

    def test_captures_valid_pcap(self):
        """Each pcap must have valid magic, contain packets, and include
        TCP traffic on port 9877 (verified structurally)."""
        d = '/app/captures'
        if not os.path.isdir(d):
            pytest.skip("No captures directory")
        pcaps = [f for f in os.listdir(d) if f.endswith('.pcap')]
        for pcap in pcaps:
            path = os.path.join(d, pcap)
            with open(path, 'rb') as fh:
                data = fh.read()

            # Check file size (global header = 24 bytes, need at least one packet)
            assert len(data) > 40, f"{pcap}: file too small ({len(data)} bytes)"

            # Verify pcap magic (little-endian or big-endian)
            magic = struct.unpack('<I', data[:4])[0]
            assert magic in (0xa1b2c3d4, 0xd4c3b2a1), \
                f"{pcap}: invalid pcap magic: {magic:#x}"

            # Determine byte order from magic
            if magic == 0xa1b2c3d4:
                endian = '<'
            else:
                endian = '>'

            # Parse global header (24 bytes)
            _, ver_maj, ver_min, _, _, snaplen, linktype = struct.unpack(
                f'{endian}IHHiIII', data[:24])
            assert linktype == 1, f"{pcap}: expected LINKTYPE_ETHERNET(1), got {linktype}"

            # Walk packet records and look for TCP port 9877
            found_port = False
            off = 24
            pkt_count = 0
            while off + 16 <= len(data):
                ts_sec, ts_usec, caplen, origlen = struct.unpack(
                    f'{endian}IIII', data[off:off + 16])
                pkt_data = data[off + 16:off + 16 + caplen]
                off += 16 + caplen
                pkt_count += 1

                # Parse: Ethernet(14) + IP(20) + TCP(20 min)
                if len(pkt_data) < 54:
                    continue
                eth_type = struct.unpack('!H', pkt_data[12:14])[0]
                if eth_type != 0x0800:  # IPv4
                    continue
                ip_proto = pkt_data[14 + 9]
                if ip_proto != 6:  # TCP
                    continue
                ip_ihl = (pkt_data[14] & 0x0F) * 4
                tcp_off = 14 + ip_ihl
                if tcp_off + 4 > len(pkt_data):
                    continue
                src_port, dst_port = struct.unpack(
                    '!HH', pkt_data[tcp_off:tcp_off + 4])
                if src_port == 9877 or dst_port == 9877:
                    found_port = True
                    break

            assert pkt_count > 0, f"{pcap}: no packets found"
            assert found_port, f"{pcap}: no TCP traffic on port 9877"


# ===================================================================
# CVSS assessment tests — verify severity scoring
# ===================================================================

class TestCVSSAssessment:
    """Verify findings include valid CVSS 3.1 base score assessments."""

    CVSS_VECTOR_RE = re.compile(
        r'^CVSS:3\.1/AV:[NALP]/AC:[LH]/PR:[NLH]/UI:[NR]/S:[UC]/'
        r'C:[NLH]/I:[NLH]/A:[NLH]$'
    )

    def test_findings_have_cvss(self):
        d = '/app/exploits/findings'
        if not os.path.isdir(d):
            pytest.skip("No findings directory")
        json_files = [f for f in os.listdir(d) if f.endswith('.json')]
        assert len(json_files) >= 4, "Need at least 4 findings"
        for fname in json_files:
            with open(os.path.join(d, fname)) as f:
                data = json.load(f)
            # Check score
            assert 'cvss_score' in data, f"{fname}: missing cvss_score"
            score = float(data['cvss_score'])
            assert 0.0 <= score <= 10.0, f"{fname}: CVSS score {score} out of range"
            # Check vector
            assert 'cvss_vector' in data, f"{fname}: missing cvss_vector"
            vec = data['cvss_vector']
            assert self.CVSS_VECTOR_RE.match(vec), \
                f"{fname}: invalid CVSS 3.1 vector: {vec}"


# ===================================================================
# Hardened server tests — conformance + exploit rejection
# ===================================================================

class TestHardenedConformance:
    """Verify the hardened server passes the conformance test suite."""

    def test_conformance_passes(self, hardened_server):
        """Run conformance.py against the hardened server."""
        env = os.environ.copy()
        env['VLSP_PORT'] = str(HARDENED_PORT)
        r = subprocess.run(
            [sys.executable, '/app/voicelink/conformance.py'],
            capture_output=True, text=True, timeout=30, env=env)
        assert r.returncode == 0, \
            f"Conformance suite failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"


class TestHardenedRejectsExploits:
    """Verify the hardened server rejects all 4 exploit patterns."""

    def test_hardened_rejects_connect_spoofing(self, hardened_server):
        """CONNECT from caller must be rejected or must NOT transmit callee media."""
        c = VLSPClient(HARDENED_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller, {'display_name': 'a'})
            c.transact(MsgType.REGISTER, z, callee, {'display_name': 'b'})
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
            _, _, _, resp = c.transact(MsgType.CONNECT, sid, caller, {})
            if resp.get('status') == 'ok':
                tx, _ = _callee_media_status(c, sid, caller)
                assert not tx, "Hardened server must NOT transmit callee media on caller CONNECT"
            # status == 'error' is also acceptable (exploit rejected)
        finally:
            c.close()

    def test_hardened_rejects_embedded_candidates(self, hardened_server):
        """Inline ICE candidates must NOT cause premature callee media."""
        c = VLSPClient(HARDENED_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller, {'display_name': 'a'})
            c.transact(MsgType.REGISTER, z, callee, {'display_name': 'b'})
            sdp = ('v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'
                   'a=candidate:1 1 udp 2130706431 10.0.0.1 50000 typ host\r\n')
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': sdp})
            tx, _ = _callee_media_status(c, sid, caller)
            assert not tx, "Hardened server must NOT transmit callee media from inline candidates"
        finally:
            c.close()

    def test_hardened_rejects_sdp_update_ringing(self, hardened_server):
        """SDP_UPDATE must NOT activate media for multi-device callee in RINGING."""
        c = VLSPClient(HARDENED_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller,
                       {'display_name': 'a', 'device_count': 1})
            c.transact(MsgType.REGISTER, z, callee,
                       {'display_name': 'b', 'device_count': 2})
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
            c.transact(MsgType.CANDIDATE, sid, caller,
                       {'candidate': 'candidate:1 1 udp 2130706431 10.0.0.1 5000 typ host'})
            c.transact(MsgType.SDP_UPDATE, sid, caller,
                       {'sdp': 'v=0\r\n', 'reason': 'add_video'})
            tx, _ = _callee_media_status(c, sid, caller)
            assert not tx, "Hardened server must NOT transmit callee media on SDP_UPDATE in RINGING"
        finally:
            c.close()

    def test_hardened_rejects_type_confusion(self, hardened_server):
        """String media_policy must NOT bypass consent."""
        c = VLSPClient(HARDENED_PORT)
        try:
            caller, callee, sid = make_id(), make_id(), make_id()
            z = b'\x00' * 12
            c.transact(MsgType.REGISTER, z, caller, {'display_name': 'a'})
            c.transact(MsgType.REGISTER, z, callee, {'display_name': 'b'})
            c.transact(MsgType.OFFER, sid, caller,
                       {'callee_id': callee.hex(), 'sdp': 'v=0\r\n'})
            c.transact(MsgType.MEDIA_CONFIG, sid, caller,
                       {'media_policy': 'auto_enable'})
            tx, _ = _callee_media_status(c, sid, caller)
            assert not tx, "Hardened server must NOT transmit callee media on string media_policy"
        finally:
            c.close()

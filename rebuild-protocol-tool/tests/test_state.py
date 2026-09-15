
import subprocess
import struct
import os
import tempfile
import hashlib
import pytest

LFSR_POLY = 0xB4BCD35C
LFSR_ZERO_SEED = 0x0000ACE1


def crc16_ccitt(data):
    """CRC-16/CCITT-FALSE: poly=0x1021, init=0xFFFF, no reflection."""
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


def build_packet(msg_type, payload):
    """Build a valid MLP packet with correct CRC."""
    header = bytearray(8)
    header[0:2] = b'ML'
    header[2] = 1  # version
    header[3] = msg_type
    struct.pack_into('>H', header, 4, len(payload))
    # CRC over header[2:6] + payload
    crc_data = bytes(header[2:6]) + payload
    crc = crc16_ccitt(crc_data)
    struct.pack_into('>H', header, 6, crc)
    return bytes(header) + payload


def build_packet_bad_crc(msg_type, payload, bad_crc):
    """Build an MLP packet with a specified (incorrect) CRC."""
    header = bytearray(8)
    header[0:2] = b'ML'
    header[2] = 1
    header[3] = msg_type
    struct.pack_into('>H', header, 4, len(payload))
    struct.pack_into('>H', header, 6, bad_crc)
    return bytes(header) + payload


def lfsr_scramble(data, seq):
    """Scramble/descramble using Galois LFSR keystream.

    Galois LFSR with right-shift and polynomial 0xB4BCD35C.
    Seed = sequence number (zero-seed falls back to 0xACE1).
    Each byte: advance LFSR, XOR data with low byte of state.
    """
    state = seq if seq != 0 else LFSR_ZERO_SEED
    result = bytearray(len(data))
    for i in range(len(data)):
        lsb = state & 1
        state >>= 1
        if lsb:
            state ^= LFSR_POLY
        state &= 0xFFFFFFFF
        result[i] = data[i] ^ (state & 0xFF)
    return bytes(result)


def run_pktool(args):
    return subprocess.run(
        ['/app/pktool'] + args,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def write_bin(tmpdir, data, name='test.bin'):
    path = os.path.join(tmpdir, name)
    with open(path, 'wb') as f:
        f.write(data)
    return path


# ---------------------------------------------------------------------------
# Anti-cheat
# ---------------------------------------------------------------------------
class TestSetup:
    def test_pktool_exists_and_executable(self):
        assert os.path.exists('/app/pktool'), "/app/pktool not found"
        assert os.access('/app/pktool', os.X_OK), "/app/pktool is not executable"

    def test_not_reference_copy(self):
        if not os.path.exists('/app/pktool-ref'):
            return  # reference may have been removed; skip
        ref = open('/app/pktool-ref', 'rb').read()
        impl = open('/app/pktool', 'rb').read()
        assert hashlib.sha256(impl).digest() != hashlib.sha256(ref).digest(), \
            "/app/pktool must not be a byte-for-byte copy of the reference binary"


# ---------------------------------------------------------------------------
# Decode tests
# ---------------------------------------------------------------------------
class TestDecode:
    def test_hello(self, tmpdir):
        payload = struct.pack('>I', 0xDEADBEEF) + b'router-alpha\x00'
        path = write_bin(tmpdir, build_packet(0, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Packet #1:' in r.stdout
        assert 'Type: HELLO (0)' in r.stdout
        assert 'Node ID: 0xDEADBEEF' in r.stdout
        assert 'Node Name: "router-alpha"' in r.stdout

    def test_data(self, tmpdir):
        payload = struct.pack('>B', 5) + struct.pack('>I', 999) + bytes.fromhex('cafebabe')
        path = write_bin(tmpdir, build_packet(1, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Type: DATA (1)' in r.stdout
        assert 'Channel: 5' in r.stdout
        assert 'Sequence: 999' in r.stdout
        assert 'cafebabe' in r.stdout
        assert '4 bytes' in r.stdout

    def test_ack(self, tmpdir):
        payload = struct.pack('>I', 42)
        path = write_bin(tmpdir, build_packet(2, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Type: ACK (2)' in r.stdout
        assert 'Sequence: 42' in r.stdout

    def test_error_msg(self, tmpdir):
        payload = struct.pack('>H', 0x00FF) + b'timeout exceeded'
        path = write_bin(tmpdir, build_packet(3, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Type: ERROR (3)' in r.stdout
        assert 'Error Code: 0x00FF' in r.stdout
        assert 'Error Message: "timeout exceeded"' in r.stdout

    def test_route(self, tmpdir):
        payload = struct.pack('>B', 2) + struct.pack('>III', 0xA, 0xB, 0xC)
        path = write_bin(tmpdir, build_packet(4, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Type: ROUTE (4)' in r.stdout
        assert 'Hop Count: 2' in r.stdout
        assert '0x0000000A' in r.stdout
        assert '0x0000000B' in r.stdout
        assert '0x0000000C' in r.stdout

    def test_fragment(self, tmpdir):
        frag_payload = struct.pack('>I', 0x1234) + struct.pack('>HH', 1, 4) + b'\xaa\xbb'
        path = write_bin(tmpdir, build_packet(5, frag_payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Type: FRAGMENT (5)' in r.stdout
        assert 'Message ID: 0x00001234' in r.stdout
        assert 'Fragment: 1/4' in r.stdout
        assert 'aabb' in r.stdout
        assert '2 bytes' in r.stdout

    def test_multiple_packets(self, tmpdir):
        data = bytearray()
        data.extend(build_packet(2, struct.pack('>I', 10)))
        data.extend(build_packet(2, struct.pack('>I', 20)))
        data.extend(build_packet(2, struct.pack('>I', 30)))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Packet #1:' in r.stdout
        assert 'Packet #2:' in r.stdout
        assert 'Packet #3:' in r.stdout
        assert 'Sequence: 10' in r.stdout
        assert 'Sequence: 20' in r.stdout
        assert 'Sequence: 30' in r.stdout

    def test_truncated_header(self, tmpdir):
        path = write_bin(tmpdir, b'ML\x01\x01\x00\x04')
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert '[TRUNCATED]' in r.stdout

    def test_invalid_magic_recovery(self, tmpdir):
        data = bytearray()
        data.extend(b'ZZ\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        data.extend(build_packet(2, struct.pack('>I', 77)))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'INVALID MAGIC' in r.stdout
        assert 'Sequence: 77' in r.stdout

    def test_crc_mismatch(self, tmpdir):
        payload = struct.pack('>I', 99)
        pkt = build_packet_bad_crc(2, payload, 0x0000)
        crc_data = bytes([1, 2, 0, 4]) + payload
        correct_crc = crc16_ccitt(crc_data)
        path = write_bin(tmpdir, pkt)
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'CRC: INVALID' in r.stdout
        assert 'expected 0x0000' in r.stdout
        assert f'computed 0x{correct_crc:04X}' in r.stdout

    def test_hello_no_null_terminator(self, tmpdir):
        payload = struct.pack('>I', 0x11111111) + b'noterm'
        path = write_bin(tmpdir, build_packet(0, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Node Name: "noterm"' in r.stdout

    def test_unknown_type(self, tmpdir):
        payload = b'\xde\xad'
        path = write_bin(tmpdir, build_packet(7, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Type: UNKNOWN (7)' in r.stdout
        assert 'dead' in r.stdout
        assert '2 bytes' in r.stdout

    def test_scrambled_data_decode(self, tmpdir):
        """DATA on scrambled channel (>=128) must show unscrambled payload via LFSR."""
        channel = 0x80
        seq = 0x11223344
        original_data = b'SecretMsg'
        scrambled = lfsr_scramble(original_data, seq)
        payload = struct.pack('>B', channel) + struct.pack('>I', seq) + scrambled
        path = write_bin(tmpdir, build_packet(1, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Channel: 128' in r.stdout
        assert f'Sequence: {seq}' in r.stdout
        assert 'Scrambled: yes' in r.stdout
        assert original_data.hex() in r.stdout
        assert f'{len(original_data)} bytes' in r.stdout

    def test_scrambled_high_channel(self, tmpdir):
        """DATA on channel 255 (all bits set) must also descramble via LFSR."""
        channel = 0xFF
        seq = 0xDEADBEEF
        original_data = b'TopSecret'
        scrambled = lfsr_scramble(original_data, seq)
        payload = struct.pack('>B', channel) + struct.pack('>I', seq) + scrambled
        path = write_bin(tmpdir, build_packet(1, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Channel: 255' in r.stdout
        assert 'Scrambled: yes' in r.stdout
        assert original_data.hex() in r.stdout

    def test_scrambled_zero_sequence(self, tmpdir):
        """DATA with seq=0 on scrambled channel triggers LFSR zero-seed fallback."""
        channel = 0x80
        seq = 0x00000000
        original_data = b'ZeroSeed!'
        scrambled = lfsr_scramble(original_data, seq)
        payload = struct.pack('>B', channel) + struct.pack('>I', seq) + scrambled
        path = write_bin(tmpdir, build_packet(1, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Scrambled: yes' in r.stdout
        assert original_data.hex() in r.stdout

    def test_scrambled_long_payload(self, tmpdir):
        """LFSR keystream must remain correct over longer payloads (>32 bytes)."""
        channel = 0x80
        seq = 0xCAFEBABE
        original_data = bytes(range(256)) * 2  # 512 bytes of varied data
        scrambled = lfsr_scramble(original_data, seq)
        payload = struct.pack('>B', channel) + struct.pack('>I', seq) + scrambled
        path = write_bin(tmpdir, build_packet(1, payload))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Scrambled: yes' in r.stdout
        assert original_data.hex() in r.stdout
        assert f'{len(original_data)} bytes' in r.stdout


# ---------------------------------------------------------------------------
# Validate tests
# ---------------------------------------------------------------------------
class TestValidate:
    def test_all_ok(self, tmpdir):
        data = bytearray()
        data.extend(build_packet(2, struct.pack('>I', 1)))
        data.extend(build_packet(2, struct.pack('>I', 2)))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['validate', path])
        assert r.returncode == 0
        assert 'Packet #1: OK' in r.stdout
        assert 'Packet #2: OK' in r.stdout

    def test_crc_error_exit_code(self, tmpdir):
        payload = struct.pack('>I', 1)
        pkt = build_packet_bad_crc(2, payload, 0xBEEF)
        path = write_bin(tmpdir, pkt)
        r = run_pktool(['validate', path])
        assert r.returncode == 1
        assert 'CRC_MISMATCH' in r.stdout

    def test_truncated_exit_code(self, tmpdir):
        data = build_packet(2, struct.pack('>I', 1)) + b'ML\x01\x01\x00\x20'
        path = write_bin(tmpdir, data)
        r = run_pktool(['validate', path])
        assert r.returncode == 1
        assert 'Packet #1: OK' in r.stdout
        assert 'TRUNCATED' in r.stdout

    def test_scrambled_data_validates_ok(self, tmpdir):
        """Scrambled DATA with correct CRC should validate OK (CRC covers scrambled bytes)."""
        channel = 0x80
        seq = 0x12345678
        original = b'ValidateMe'
        scrambled = lfsr_scramble(original, seq)
        payload = struct.pack('>B', channel) + struct.pack('>I', seq) + scrambled
        pkt = build_packet(1, payload)
        path = write_bin(tmpdir, pkt)
        r = run_pktool(['validate', path])
        assert r.returncode == 0
        assert 'Packet #1: OK' in r.stdout


# ---------------------------------------------------------------------------
# Stats tests
# ---------------------------------------------------------------------------
class TestStats:
    def test_basic_counts(self, tmpdir):
        data = bytearray()
        data.extend(build_packet(0, struct.pack('>I', 1) + b'a\x00'))
        data.extend(build_packet(1, struct.pack('>BI', 0, 0) + b'x'))
        data.extend(build_packet(1, struct.pack('>BI', 1, 1) + b'y'))
        data.extend(build_packet(2, struct.pack('>I', 0)))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['stats', path])
        assert r.returncode == 0
        assert 'Total packets: 4' in r.stdout
        assert 'HELLO: 1' in r.stdout
        assert 'DATA: 2' in r.stdout
        assert 'ACK: 1' in r.stdout
        assert 'ERROR: 0' in r.stdout
        assert 'ROUTE: 0' in r.stdout
        assert 'FRAGMENT: 0' in r.stdout
        assert 'Invalid packets: 0' in r.stdout

    def test_stats_with_invalids(self, tmpdir):
        data = bytearray()
        data.extend(build_packet(2, struct.pack('>I', 1)))
        data.extend(build_packet_bad_crc(2, struct.pack('>I', 2), 0x0000))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['stats', path])
        assert r.returncode == 0
        assert 'Total packets: 2' in r.stdout
        assert 'ACK: 2' in r.stdout
        assert 'Invalid packets: 1' in r.stdout

    def test_stats_with_scrambled(self, tmpdir):
        """Stats should report scrambled DATA packet count when present."""
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 5, 1) + b'normal'))
        seq = 0x12345678
        original = b'secret'
        scrambled = lfsr_scramble(original, seq)
        data.extend(build_packet(1, struct.pack('>B', 0x80) + struct.pack('>I', seq) + scrambled))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['stats', path])
        assert r.returncode == 0
        assert 'Total packets: 2' in r.stdout
        assert 'DATA: 2' in r.stdout
        assert 'Scrambled DATA packets: 1' in r.stdout


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------
class TestFilter:
    def test_filter_by_type(self, tmpdir):
        data = bytearray()
        data.extend(build_packet(0, struct.pack('>I', 1) + b'n\x00'))
        data.extend(build_packet(1, struct.pack('>BI', 0, 10) + b'hello'))
        data.extend(build_packet(2, struct.pack('>I', 10)))
        data.extend(build_packet(1, struct.pack('>BI', 1, 20) + b'world'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['filter', 'type=DATA', path])
        assert r.returncode == 0
        assert 'DATA' in r.stdout
        assert 'HELLO' not in r.stdout
        assert 'ACK' not in r.stdout
        assert 'Sequence: 10' in r.stdout
        assert 'Sequence: 20' in r.stdout

    def test_filter_combined(self, tmpdir):
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 1, 10) + b'a'))
        data.extend(build_packet(1, struct.pack('>BI', 2, 20) + b'b'))
        data.extend(build_packet(1, struct.pack('>BI', 1, 30) + b'c'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['filter', 'type=DATA,channel=1', path])
        assert r.returncode == 0
        assert 'Sequence: 10' in r.stdout
        assert 'Sequence: 30' in r.stdout
        assert 'Sequence: 20' not in r.stdout

    def test_filter_no_match(self, tmpdir):
        data = build_packet(2, struct.pack('>I', 1))
        path = write_bin(tmpdir, data)
        r = run_pktool(['filter', 'type=DATA', path])
        assert r.returncode == 0
        assert 'No matching packets.' in r.stdout

    def test_filter_renumbers(self, tmpdir):
        """Filtered output should renumber packets sequentially from 1."""
        data = bytearray()
        data.extend(build_packet(0, struct.pack('>I', 1) + b'x\x00'))
        data.extend(build_packet(2, struct.pack('>I', 10)))
        data.extend(build_packet(0, struct.pack('>I', 2) + b'y\x00'))
        data.extend(build_packet(2, struct.pack('>I', 20)))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['filter', 'type=ACK', path])
        assert r.returncode == 0
        assert 'Packet #1:' in r.stdout
        assert 'Packet #2:' in r.stdout
        assert 'Packet #3:' not in r.stdout
        assert 'Packet #4:' not in r.stdout

    def test_filter_scrambled_channel(self, tmpdir):
        """Filter by channel should work for scrambled channels and show unscrambled data."""
        data = bytearray()
        seq = 0xAABBCCDD
        original = b'FilterTest'
        scrambled = lfsr_scramble(original, seq)
        data.extend(build_packet(1, struct.pack('>B', 0x80) + struct.pack('>I', seq) + scrambled))
        data.extend(build_packet(1, struct.pack('>BI', 5, 100) + b'plain'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['filter', 'channel=128', path])
        assert r.returncode == 0
        assert 'Channel: 128' in r.stdout
        assert 'Scrambled: yes' in r.stdout
        assert original.hex() in r.stdout
        assert 'Channel: 5' not in r.stdout


# ---------------------------------------------------------------------------
# CRC verification
# ---------------------------------------------------------------------------
class TestCRC:
    def test_crc_correct_computation(self, tmpdir):
        """Verify that a packet built with our CRC helper is accepted."""
        payload = struct.pack('>I', 0)
        pkt = build_packet(2, payload)
        path = write_bin(tmpdir, pkt)
        r = run_pktool(['validate', path])
        assert r.returncode == 0
        assert 'OK' in r.stdout

    def test_crc_covers_correct_bytes(self, tmpdir):
        """Ensure CRC is over version+type+payload_len+payload, NOT magic."""
        payload = struct.pack('>I', 0)
        correct_input = bytes([1, 2, 0, 4]) + payload
        correct_crc = crc16_ccitt(correct_input)
        wrong_input = b'ML' + bytes([1, 2, 0, 4]) + payload
        wrong_crc = crc16_ccitt(wrong_input)
        assert correct_crc != wrong_crc, "Test precondition: CRCs should differ"
        pkt = build_packet_bad_crc(2, payload, wrong_crc)
        path = write_bin(tmpdir, pkt)
        r = run_pktool(['validate', path])
        assert r.returncode == 1
        assert 'CRC_MISMATCH' in r.stdout


# ---------------------------------------------------------------------------
# Sequence gap detection tests
# ---------------------------------------------------------------------------
class TestSequenceGap:
    def test_gap_detected(self, tmpdir):
        """Non-contiguous sequence numbers on same channel emit gap warning."""
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 5, 100) + b'first'))
        data.extend(build_packet(1, struct.pack('>BI', 5, 102) + b'third'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Sequence gap on channel 5: expected 101, got 102' in r.stdout

    def test_no_gap_contiguous(self, tmpdir):
        """Contiguous sequence numbers should not show gap warning."""
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 5, 100) + b'first'))
        data.extend(build_packet(1, struct.pack('>BI', 5, 101) + b'second'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Sequence gap' not in r.stdout

    def test_gap_per_channel_independent(self, tmpdir):
        """Gap detection is per-channel; different channels are independent."""
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 1, 100) + b'a'))
        data.extend(build_packet(1, struct.pack('>BI', 2, 200) + b'b'))
        data.extend(build_packet(1, struct.pack('>BI', 1, 101) + b'c'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Sequence gap' not in r.stdout

    def test_gap_not_in_filter(self, tmpdir):
        """Filter command should NOT show gap warnings (no stateful tracking)."""
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 5, 100) + b'a'))
        data.extend(build_packet(1, struct.pack('>BI', 5, 200) + b'b'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['filter', 'type=DATA', path])
        assert r.returncode == 0
        assert 'Sequence gap' not in r.stdout

    def test_gap_large_jump(self, tmpdir):
        """Large sequence jump should still be reported."""
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 3, 10) + b'x'))
        data.extend(build_packet(1, struct.pack('>BI', 3, 1000) + b'y'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Sequence gap on channel 3: expected 11, got 1000' in r.stdout

    def test_no_gap_first_packet(self, tmpdir):
        """First DATA packet on a channel never triggers gap."""
        data = bytearray()
        data.extend(build_packet(1, struct.pack('>BI', 7, 999) + b'only'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['decode', path])
        assert r.returncode == 0
        assert 'Sequence gap' not in r.stdout


# ---------------------------------------------------------------------------
# Reassemble tests
# ---------------------------------------------------------------------------
class TestReassemble:
    def test_reassemble_complete(self, tmpdir):
        """Complete fragment set should show concatenated hex data."""
        data = bytearray()
        data.extend(build_packet(5, struct.pack('>I', 0x2000) + struct.pack('>HH', 0, 3) + b'Hello, '))
        data.extend(build_packet(5, struct.pack('>I', 0x2000) + struct.pack('>HH', 1, 3) + b'MeshLink '))
        data.extend(build_packet(5, struct.pack('>I', 0x2000) + struct.pack('>HH', 2, 3) + b'Protocol!'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert '0x00002000' in r.stdout
        assert 'COMPLETE' in r.stdout
        assert '3/3' in r.stdout
        full_data = b'Hello, MeshLink Protocol!'
        assert full_data.hex() in r.stdout
        assert f'{len(full_data)} bytes' in r.stdout

    def test_reassemble_incomplete(self, tmpdir):
        """Missing fragments should be reported with their indices."""
        data = bytearray()
        data.extend(build_packet(5, struct.pack('>I', 0x3000) + struct.pack('>HH', 0, 4) + b'A'))
        data.extend(build_packet(5, struct.pack('>I', 0x3000) + struct.pack('>HH', 2, 4) + b'C'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert '0x00003000' in r.stdout
        assert 'INCOMPLETE' in r.stdout
        assert '2/4' in r.stdout
        assert 'missing: 1, 3' in r.stdout

    def test_reassemble_out_of_order(self, tmpdir):
        """Out-of-order fragments should be correctly reassembled."""
        data = bytearray()
        data.extend(build_packet(5, struct.pack('>I', 0x4000) + struct.pack('>HH', 2, 3) + b'CCC'))
        data.extend(build_packet(5, struct.pack('>I', 0x4000) + struct.pack('>HH', 0, 3) + b'AAA'))
        data.extend(build_packet(5, struct.pack('>I', 0x4000) + struct.pack('>HH', 1, 3) + b'BBB'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert 'COMPLETE' in r.stdout
        expected = b'AAABBBCCC'
        assert expected.hex() in r.stdout

    def test_reassemble_no_fragments(self, tmpdir):
        """File with no FRAGMENT packets should report accordingly."""
        data = build_packet(2, struct.pack('>I', 1))
        path = write_bin(tmpdir, data)
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert 'No fragment packets found.' in r.stdout

    def test_reassemble_multiple_messages(self, tmpdir):
        """Multiple message IDs should be output sorted by ID."""
        data = bytearray()
        data.extend(build_packet(5, struct.pack('>I', 0x1000) + struct.pack('>HH', 0, 2) + b'AB'))
        data.extend(build_packet(5, struct.pack('>I', 0x1000) + struct.pack('>HH', 1, 2) + b'CD'))
        data.extend(build_packet(5, struct.pack('>I', 0x2000) + struct.pack('>HH', 0, 3) + b'X'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert '0x00001000' in r.stdout
        assert 'COMPLETE' in r.stdout
        assert '0x00002000' in r.stdout
        assert 'INCOMPLETE' in r.stdout
        pos1 = r.stdout.index('0x00001000')
        pos2 = r.stdout.index('0x00002000')
        assert pos1 < pos2

    def test_reassemble_duplicate_fragments(self, tmpdir):
        """Duplicate fragment indices should be deduplicated (first occurrence kept)."""
        data = bytearray()
        data.extend(build_packet(5, struct.pack('>I', 0x5000) + struct.pack('>HH', 0, 2) + b'AA'))
        data.extend(build_packet(5, struct.pack('>I', 0x5000) + struct.pack('>HH', 0, 2) + b'AA'))
        data.extend(build_packet(5, struct.pack('>I', 0x5000) + struct.pack('>HH', 1, 2) + b'BB'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert 'COMPLETE' in r.stdout
        assert '2/2' in r.stdout
        expected = b'AABB'
        assert expected.hex() in r.stdout

    def test_reassemble_ignores_crc_bad(self, tmpdir):
        """Fragments with CRC errors should be excluded from reassembly."""
        data = bytearray()
        data.extend(build_packet(5, struct.pack('>I', 0x6000) + struct.pack('>HH', 0, 2) + b'OK'))
        data.extend(build_packet_bad_crc(5,
            struct.pack('>I', 0x6000) + struct.pack('>HH', 1, 2) + b'BAD', 0x0000))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert 'INCOMPLETE' in r.stdout
        assert '1/2' in r.stdout

    def test_reassemble_conflicting_totals(self, tmpdir):
        """Fragments with different total counts trigger warning; max total is used."""
        data = bytearray()
        # Fragment 0 says total=2, fragment 1 says total=4
        data.extend(build_packet(5, struct.pack('>I', 0x7000) + struct.pack('>HH', 0, 2) + b'AA'))
        data.extend(build_packet(5, struct.pack('>I', 0x7000) + struct.pack('>HH', 1, 4) + b'BB'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert 'inconsistent fragment counts' in r.stdout
        assert 'INCOMPLETE' in r.stdout
        assert '2/4' in r.stdout
        assert 'missing: 2, 3' in r.stdout

    def test_reassemble_consistent_totals_no_warning(self, tmpdir):
        """Fragments with matching totals should NOT show conflict warning."""
        data = bytearray()
        data.extend(build_packet(5, struct.pack('>I', 0x8000) + struct.pack('>HH', 0, 2) + b'XX'))
        data.extend(build_packet(5, struct.pack('>I', 0x8000) + struct.pack('>HH', 1, 2) + b'YY'))
        path = write_bin(tmpdir, bytes(data))
        r = run_pktool(['reassemble', path])
        assert r.returncode == 0
        assert 'COMPLETE' in r.stdout
        assert 'inconsistent' not in r.stdout
        assert 'Warning' not in r.stdout


import struct
import socket
import subprocess
import os
import shutil
import pytest


def compute_checksum(data: bytes) -> int:
    """Compute Internet checksum (RFC 1071) over data bytes."""
    if len(data) % 2:
        data = data + b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def make_timestamp_option(tsval, tsecr):
    """Build NOP+NOP+Timestamp TCP option (12 bytes, 4-byte aligned)."""
    return struct.pack('!BBBBII', 1, 1, 8, 10, tsval, tsecr)


def make_packet(src_ip, src_port, dst_ip, dst_port, seq, ack, flags,
                data=b'', window=65535, options=b''):
    """Build a raw IPv4/TCP packet with correct checksums.

    flags: string with flag chars - S=SYN, A=ACK, F=FIN, R=RST, P=PSH
    options: raw TCP options bytes (will be padded to 4-byte boundary)
    """
    # Pad options to 4-byte boundary
    opt_padded = options
    while len(opt_padded) % 4:
        opt_padded += b'\x00'

    flag_byte = 0
    if 'F' in flags:
        flag_byte |= 0x01
    if 'S' in flags:
        flag_byte |= 0x02
    if 'R' in flags:
        flag_byte |= 0x04
    if 'P' in flags:
        flag_byte |= 0x08
    if 'A' in flags:
        flag_byte |= 0x10

    data_offset = (20 + len(opt_padded)) // 4
    offset_reserved = (data_offset << 4) & 0xF0

    # 20-byte fixed TCP header + options
    tcp_hdr = struct.pack('!HHIIBBHHH',
                          src_port, dst_port,
                          seq & 0xFFFFFFFF, ack & 0xFFFFFFFF,
                          offset_reserved, flag_byte,
                          window, 0, 0)
    tcp_hdr += opt_padded

    # TCP checksum with pseudo-header
    tcp_len = len(tcp_hdr) + len(data)
    pseudo = (socket.inet_aton(src_ip) + socket.inet_aton(dst_ip) +
              struct.pack('!BBH', 0, 6, tcp_len))
    tcp_cksum = compute_checksum(pseudo + tcp_hdr + data)
    tcp_hdr = tcp_hdr[:16] + struct.pack('!H', tcp_cksum) + tcp_hdr[18:]

    # IPv4 header
    tcp_payload = tcp_hdr + data
    total_len = 20 + len(tcp_payload)
    ip_hdr = struct.pack('!BBHHHBBH',
                         0x45, 0, total_len,
                         0, 0x4000,
                         64, 6, 0)
    ip_hdr += socket.inet_aton(src_ip) + socket.inet_aton(dst_ip)
    ip_cksum = compute_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('!H', ip_cksum) + ip_hdr[12:]

    return ip_hdr + tcp_payload


def write_capture(filename, packets):
    """Write packets to capture file: [4-byte BE length][packet] ..."""
    with open(filename, 'wb') as f:
        for pkt in packets:
            f.write(struct.pack('!I', len(pkt)))
            f.write(pkt)


def run_reassemble(capture_file, output_dir):
    """Run the reassemble program."""
    os.makedirs(output_dir, exist_ok=True)
    result = subprocess.run(
        ['/app/reassemble', capture_file, output_dir],
        capture_output=True, text=True, timeout=30)
    return result


def read_file_bin(path):
    with open(path, 'rb') as f:
        return f.read()


def read_info(output_dir, conn_idx):
    info = {}
    path = os.path.join(output_dir, f'conn_{conn_idx}_info.txt')
    with open(path) as f:
        for line in f:
            line = line.strip()
            if '=' in line:
                k, v = line.split('=', 1)
                info[k] = v
    return info


def handshake(src_ip, src_port, dst_ip, dst_port, client_isn, server_isn,
              options=b''):
    """3-way handshake packets."""
    return [
        make_packet(src_ip, src_port, dst_ip, dst_port,
                    client_isn, 0, 'S', options=options),
        make_packet(dst_ip, dst_port, src_ip, src_port,
                    server_isn, client_isn + 1, 'SA', options=options),
        make_packet(src_ip, src_port, dst_ip, dst_port,
                    client_isn + 1, server_isn + 1, 'A', options=options),
    ]


def fin_close(src_ip, src_port, dst_ip, dst_port, client_seq, server_seq,
              options=b''):
    """4-packet FIN exchange to close a connection."""
    return [
        make_packet(src_ip, src_port, dst_ip, dst_port,
                    client_seq, server_seq, 'FA', options=options),
        make_packet(dst_ip, dst_port, src_ip, src_port,
                    server_seq, client_seq + 1, 'A', options=options),
        make_packet(dst_ip, dst_port, src_ip, src_port,
                    server_seq, client_seq + 1, 'FA', options=options),
        make_packet(src_ip, src_port, dst_ip, dst_port,
                    client_seq + 1, server_seq + 1, 'A', options=options),
    ]


# ========================== Tests ==========================


def test_simple_connection():
    """Basic connection with bidirectional data."""
    capture = '/tmp/test_simple.bin'
    outdir = '/tmp/test_simple_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40000, 80
    CI, SI = 1000, 2000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'Hello, Server!'),
        make_packet(S, SP, C, CP, SI + 1, CI + 15, 'A'),
        make_packet(S, SP, C, CP, SI + 1, CI + 15, 'PA', b'Hello, Client!'),
        make_packet(C, CP, S, SP, CI + 15, SI + 15, 'A'),
        *fin_close(C, CP, S, SP, CI + 15, SI + 15),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0, f"reassemble failed: {result.stderr}"

    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'Hello, Server!'
    assert read_file_bin(f'{outdir}/conn_0_rev.bin') == b'Hello, Client!'

    info = read_info(outdir, 0)
    assert info['SRC'] == '10.0.0.1:40000'
    assert info['DST'] == '10.0.0.2:80'
    assert info['FWD_BYTES'] == '14'
    assert info['REV_BYTES'] == '14'
    assert info['RETRANSMISSIONS'] == '0'
    assert info['INJECTIONS'] == '0'
    assert info['STATE'] == 'CLOSED'


def test_out_of_order():
    """Segments arrive in wrong order; reassembled data must be correct."""
    capture = '/tmp/test_ooo.bin'
    outdir = '/tmp/test_ooo_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40001, 80
    CI, SI = 5000, 6000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        # 3 x 10-byte chunks arrive as: chunk3, chunk1, chunk2
        make_packet(C, CP, S, SP, CI + 21, SI + 1, 'PA', b'CCCCCCCCCC'),
        make_packet(C, CP, S, SP, CI + 1,  SI + 1, 'PA', b'AAAAAAAAAA'),
        make_packet(C, CP, S, SP, CI + 11, SI + 1, 'PA', b'BBBBBBBBBB'),
        make_packet(S, SP, C, CP, SI + 1, CI + 31, 'A'),
        *fin_close(C, CP, S, SP, CI + 31, SI + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    expected = b'AAAAAAAAAABBBBBBBBBBCCCCCCCCCC'
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == expected

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '30'
    assert info['REV_BYTES'] == '0'
    assert info['RETRANSMISSIONS'] == '0'
    assert info['INJECTIONS'] == '0'
    assert info['STATE'] == 'CLOSED'


def test_retransmission():
    """Exact duplicate segment detected as retransmission, not injection."""
    capture = '/tmp/test_retrans.bin'
    outdir = '/tmp/test_retrans_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40002, 80
    CI, SI = 3000, 4000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'RETRANSMIT'),
        # Exact same segment again
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'RETRANSMIT'),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'A'),
        *fin_close(C, CP, S, SP, CI + 11, SI + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'RETRANSMIT'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '10'
    assert info['RETRANSMISSIONS'] == '1'
    assert info['INJECTIONS'] == '0'
    assert info['STATE'] == 'CLOSED'


def test_seq_wraparound():
    """Sequence numbers that wrap around the 32-bit unsigned boundary.

    ISN near 0xFFFFFFFF means data sequence numbers cross from
    0xFFFFFFxx to 0x000000xx. Naive unsigned comparisons fail here;
    correct implementation requires modular arithmetic.
    """
    capture = '/tmp/test_wrap.bin'
    outdir = '/tmp/test_wrap_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40003, 80
    CI = 0xFFFFFFF0  # ISN near max uint32
    SI = 2000

    # Data starts at CI+1 = 0xFFFFFFF1
    # Chunk1: seq 0xFFFFFFF1, 10 bytes -> ends at 0xFFFFFFFA
    # Chunk2: seq 0xFFFFFFFB, 10 bytes -> wraps to 0x00000004
    # Chunk3: seq 0x00000005, 10 bytes -> ends at 0x0000000E
    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'AAAAAAAAAA'),
        make_packet(C, CP, S, SP, CI + 11, SI + 1, 'PA', b'BBBBBBBBBB'),
        make_packet(C, CP, S, SP, CI + 21, SI + 1, 'PA', b'CCCCCCCCCC'),
        make_packet(S, SP, C, CP, SI + 1, CI + 31, 'A'),
        *fin_close(C, CP, S, SP, CI + 31, SI + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    expected = b'AAAAAAAAAABBBBBBBBBBCCCCCCCCCC'
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == expected

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '30'
    assert info['RETRANSMISSIONS'] == '0'
    assert info['INJECTIONS'] == '0'
    assert info['STATE'] == 'CLOSED'


def test_ooo_wraparound():
    """Out-of-order delivery combined with sequence number wraparound.

    Segments arrive: chunk3 (seq 0x0A), chunk1 (seq 0xFFFFFFF6),
    chunk2 (seq 0x00000000). Naive sort by raw seq puts chunk2 and
    chunk3 before chunk1. Correct ISN-relative sort is required.
    """
    capture = '/tmp/test_ooo_wrap.bin'
    outdir = '/tmp/test_ooo_wrap_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40004, 80
    CI = 0xFFFFFFF5
    SI = 2000

    # Data starts at CI+1 = 0xFFFFFFF6
    # chunk1 offset 1:  seq = 0xFFFFFFF6
    # chunk2 offset 11: seq = 0x00000000 (wraps through zero!)
    # chunk3 offset 21: seq = 0x0000000A
    # Arrive as: chunk3, chunk1, chunk2
    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 21, SI + 1, 'PA', b'CCCCCCCCCC'),
        make_packet(C, CP, S, SP, CI + 1,  SI + 1, 'PA', b'AAAAAAAAAA'),
        make_packet(C, CP, S, SP, CI + 11, SI + 1, 'PA', b'BBBBBBBBBB'),
        make_packet(S, SP, C, CP, SI + 1, CI + 31, 'A'),
        *fin_close(C, CP, S, SP, CI + 31, SI + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    expected = b'AAAAAAAAAABBBBBBBBBBCCCCCCCCCC'
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == expected

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '30'
    assert info['RETRANSMISSIONS'] == '0'
    assert info['INJECTIONS'] == '0'
    assert info['STATE'] == 'CLOSED'


def test_tcp_options():
    """Packets with TCP options produce variable-length headers (>20 bytes).

    All packets carry a 12-byte timestamp option, making TCP headers 32 bytes.
    The data offset field must be used to find the payload start. If the
    implementation assumes a fixed 20-byte header, option bytes will be
    incorrectly included in the reassembled data stream.
    """
    capture = '/tmp/test_opts.bin'
    outdir = '/tmp/test_opts_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 45000, 80
    CI, SI = 1000, 2000
    ts = make_timestamp_option(100, 0)

    packets = [
        *handshake(C, CP, S, SP, CI, SI, options=ts),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA',
                    b'WITH_OPTS!', options=ts),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'A', options=ts),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'PA',
                    b'OPTS_REPLY', options=ts),
        make_packet(C, CP, S, SP, CI + 11, SI + 11, 'A', options=ts),
        *fin_close(C, CP, S, SP, CI + 11, SI + 11, options=ts),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    # Only application data, no option bytes in stream
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'WITH_OPTS!'
    assert read_file_bin(f'{outdir}/conn_0_rev.bin') == b'OPTS_REPLY'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '10'
    assert info['REV_BYTES'] == '10'
    assert info['RETRANSMISSIONS'] == '0'
    assert info['INJECTIONS'] == '0'
    assert info['STATE'] == 'CLOSED'


def test_injection_detection():
    """Retransmitted segment with different payload detected as injection.

    Original data must be preserved (first-data-wins). The conflicting
    retransmission is counted as an injection, not a retransmission.
    """
    capture = '/tmp/test_inject.bin'
    outdir = '/tmp/test_inject_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40005, 80
    CI, SI = 3000, 4000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        # Original segment
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'ORIGINAL!!'),
        # Same seq and length, but different data -> injection
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'INJECTED!!'),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'A'),
        *fin_close(C, CP, S, SP, CI + 11, SI + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    # Original data preserved
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'ORIGINAL!!'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '10'
    assert info['RETRANSMISSIONS'] == '0'
    assert info['INJECTIONS'] == '1'
    assert info['STATE'] == 'CLOSED'


def test_multiple_connections():
    """Two interleaved connections tracked independently."""
    capture = '/tmp/test_multi.bin'
    outdir = '/tmp/test_multi_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    CA, SA = '10.0.0.1', '10.0.0.2'
    CPA, SPA = 50000, 80
    CIA, SIA = 7000, 8000

    CB, SB = '10.0.0.3', '10.0.0.4'
    CPB, SPB = 60000, 443
    CIB, SIB = 9000, 10000

    packets = [
        # Interleaved handshakes
        make_packet(CA, CPA, SA, SPA, CIA, 0, 'S'),
        make_packet(CB, CPB, SB, SPB, CIB, 0, 'S'),
        make_packet(SA, SPA, CA, CPA, SIA, CIA + 1, 'SA'),
        make_packet(SB, SPB, CB, CPB, SIB, CIB + 1, 'SA'),
        make_packet(CA, CPA, SA, SPA, CIA + 1, SIA + 1, 'A'),
        make_packet(CB, CPB, SB, SPB, CIB + 1, SIB + 1, 'A'),
        # Data
        make_packet(CA, CPA, SA, SPA, CIA + 1, SIA + 1, 'PA', b'ALPHA_DATA'),
        make_packet(CB, CPB, SB, SPB, CIB + 1, SIB + 1, 'PA', b'BETA_DATA!'),
        # ACKs
        make_packet(SA, SPA, CA, CPA, SIA + 1, CIA + 11, 'A'),
        make_packet(SB, SPB, CB, CPB, SIB + 1, CIB + 11, 'A'),
        # Close both
        *fin_close(CA, CPA, SA, SPA, CIA + 11, SIA + 1),
        *fin_close(CB, CPB, SB, SPB, CIB + 11, SIB + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    # Connection A = conn_0
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'ALPHA_DATA'
    info0 = read_info(outdir, 0)
    assert info0['SRC'] == '10.0.0.1:50000'
    assert info0['DST'] == '10.0.0.2:80'
    assert info0['FWD_BYTES'] == '10'
    assert info0['INJECTIONS'] == '0'
    assert info0['STATE'] == 'CLOSED'

    # Connection B = conn_1
    assert read_file_bin(f'{outdir}/conn_1_fwd.bin') == b'BETA_DATA!'
    info1 = read_info(outdir, 1)
    assert info1['SRC'] == '10.0.0.3:60000'
    assert info1['DST'] == '10.0.0.4:443'
    assert info1['FWD_BYTES'] == '10'
    assert info1['STATE'] == 'CLOSED'

    with open(f'{outdir}/summary.txt') as f:
        summary = f.read()
    assert 'CONNECTIONS=2' in summary


def test_overlapping_segments():
    """Overlapping TCP segments with matching data merged correctly."""
    capture = '/tmp/test_overlap.bin'
    outdir = '/tmp/test_overlap_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40006, 80
    CI, SI = 2000, 3000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        # Segment 1: seq CI+1, 6 bytes (offsets 0-5)
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'AAABBB'),
        # Segment 2: seq CI+4, 6 bytes (offsets 3-8), overlaps 3 bytes
        make_packet(C, CP, S, SP, CI + 4, SI + 1, 'PA', b'BBBCCC'),
        make_packet(S, SP, C, CP, SI + 1, CI + 10, 'A'),
        *fin_close(C, CP, S, SP, CI + 10, SI + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    # Overlap keeps first data; unique tail appended
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'AAABBBCCC'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '9'
    assert info['RETRANSMISSIONS'] == '0'
    assert info['INJECTIONS'] == '0'
    assert info['STATE'] == 'CLOSED'


def test_checksum_error():
    """Packets with invalid IP checksum are skipped and counted.

    A packet with a corrupted IP header checksum must be dropped silently
    and the CHECKSUM_ERRORS counter in summary.txt must be incremented.
    Valid packets in the same capture must still be processed normally.
    """
    capture = '/tmp/test_cksum.bin'
    outdir = '/tmp/test_cksum_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40007, 80
    CI, SI = 5000, 6000

    # Build a valid packet from a different 4-tuple, then corrupt its
    # IP header checksum so it fails verification.
    bad_pkt = bytearray(
        make_packet('10.0.0.5', 12345, '10.0.0.6', 80, 100, 0, 'S'))
    bad_pkt[10] ^= 0xFF  # flip a byte in the IP checksum field
    bad_pkt = bytes(bad_pkt)

    packets = [
        bad_pkt,  # should be skipped and counted
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'CHECKSUMOK'),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'A'),
        *fin_close(C, CP, S, SP, CI + 11, SI + 1),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    # Valid connection data is reassembled correctly
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'CHECKSUMOK'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '10'
    assert info['STATE'] == 'CLOSED'

    # Summary must report exactly 1 checksum error
    with open(f'{outdir}/summary.txt') as f:
        summary = f.read()
    assert 'CONNECTIONS=1' in summary
    assert 'CHECKSUM_ERRORS=1' in summary


def test_state_established():
    """Connection without FIN or RST remains in ESTABLISHED state.

    A completed handshake followed by data exchange but no teardown
    must report STATE=ESTABLISHED.
    """
    capture = '/tmp/test_estab.bin'
    outdir = '/tmp/test_estab_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40008, 80
    CI, SI = 1000, 2000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'NO_FIN_YET'),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'A'),
        # No FIN, no RST — connection stays established
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'NO_FIN_YET'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '10'
    assert info['STATE'] == 'ESTABLISHED'


def test_state_fin_wait():
    """Connection with only one FIN is in FIN_WAIT state.

    When only the client sends FIN but the server does not, the
    connection must report STATE=FIN_WAIT (half-closed).
    """
    capture = '/tmp/test_finwait.bin'
    outdir = '/tmp/test_finwait_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40009, 80
    CI, SI = 1000, 2000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'HALF_CLOSE'),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'A'),
        # Client sends FIN
        make_packet(C, CP, S, SP, CI + 11, SI + 1, 'FA'),
        make_packet(S, SP, C, CP, SI + 1, CI + 12, 'A'),
        # Server does NOT send FIN — half-closed state
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'HALF_CLOSE'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '10'
    assert info['STATE'] == 'FIN_WAIT'


def test_state_reset():
    """Connection receiving RST enters RESET state.

    After handshake and data exchange, a RST from the server must
    set STATE=RESET. Previously received data must still be present
    in the reassembled stream.
    """
    capture = '/tmp/test_rst.bin'
    outdir = '/tmp/test_rst_out'
    if os.path.exists(outdir):
        shutil.rmtree(outdir)

    C, S = '10.0.0.1', '10.0.0.2'
    CP, SP = 40010, 80
    CI, SI = 1000, 2000

    packets = [
        *handshake(C, CP, S, SP, CI, SI),
        make_packet(C, CP, S, SP, CI + 1, SI + 1, 'PA', b'THEN_RESET'),
        make_packet(S, SP, C, CP, SI + 1, CI + 11, 'RA'),
    ]

    write_capture(capture, packets)
    result = run_reassemble(capture, outdir)
    assert result.returncode == 0

    # Data received before RST is preserved
    assert read_file_bin(f'{outdir}/conn_0_fwd.bin') == b'THEN_RESET'

    info = read_info(outdir, 0)
    assert info['FWD_BYTES'] == '10'
    assert info['STATE'] == 'RESET'

"""
Tests for PCAP / MoldUDP64 / ITCH 5.0 Feed Engine.
Generates PCAP-wrapped MoldUDP64 capture data with noise traffic and verifies engine output.
"""

import pytest
import json
import struct
import subprocess
import os
import tempfile


# ===== ITCH Binary Message Builders =====

def _ts(ns):
    return ns.to_bytes(6, 'big')

def _stk(s):
    return s.ljust(8).encode('ascii')

def _p4(price):
    return struct.pack('>I', int(round(price * 10000)))

def _p8(price):
    return struct.pack('>Q', int(round(price * 1e8)))


def msg_system_event(locate, ts, event):
    m = struct.pack('>cHH', b'S', locate, 0) + _ts(ts) + event.encode('ascii')
    assert len(m) == 12
    return m

def msg_stock_directory(locate, ts, stock, mkt='Q', fin='N', lot=100):
    m = struct.pack('>cHH', b'R', locate, 0) + _ts(ts)
    m += _stk(stock) + mkt.encode() + fin.encode()
    m += struct.pack('>I', lot) + b'N' + b'C' + b'  ' + b'P' + b'N' + b'N'
    m += b' ' + b'N' + struct.pack('>I', 0) + b'N'
    assert len(m) == 39
    return m

def msg_trading_action(locate, ts, stock, state='T'):
    m = struct.pack('>cHH', b'H', locate, 0) + _ts(ts)
    m += _stk(stock) + state.encode() + b' ' + b'    '
    assert len(m) == 25
    return m

def msg_add_order(locate, ts, ref, side, shares, stock, price):
    m = struct.pack('>cHH', b'A', locate, 0) + _ts(ts)
    m += struct.pack('>Q', ref) + side.encode() + struct.pack('>I', shares)
    m += _stk(stock) + _p4(price)
    assert len(m) == 36
    return m

def msg_add_order_mpid(locate, ts, ref, side, shares, stock, price, mpid):
    m = struct.pack('>cHH', b'F', locate, 0) + _ts(ts)
    m += struct.pack('>Q', ref) + side.encode() + struct.pack('>I', shares)
    m += _stk(stock) + _p4(price) + mpid.ljust(4).encode('ascii')
    assert len(m) == 40
    return m

def msg_order_executed(locate, ts, ref, shares, match):
    m = struct.pack('>cHH', b'E', locate, 0) + _ts(ts)
    m += struct.pack('>Q', ref) + struct.pack('>I', shares) + struct.pack('>Q', match)
    assert len(m) == 31
    return m

def msg_order_executed_price(locate, ts, ref, shares, match, printable, price):
    m = struct.pack('>cHH', b'C', locate, 0) + _ts(ts)
    m += struct.pack('>Q', ref) + struct.pack('>I', shares) + struct.pack('>Q', match)
    m += printable.encode() + _p4(price)
    assert len(m) == 36
    return m

def msg_order_cancel(locate, ts, ref, shares):
    m = struct.pack('>cHH', b'X', locate, 0) + _ts(ts)
    m += struct.pack('>Q', ref) + struct.pack('>I', shares)
    assert len(m) == 23
    return m

def msg_order_delete(locate, ts, ref):
    m = struct.pack('>cHH', b'D', locate, 0) + _ts(ts)
    m += struct.pack('>Q', ref)
    assert len(m) == 19
    return m

def msg_order_replace(locate, ts, orig_ref, new_ref, shares, price):
    m = struct.pack('>cHH', b'U', locate, 0) + _ts(ts)
    m += struct.pack('>Q', orig_ref) + struct.pack('>Q', new_ref)
    m += struct.pack('>I', shares) + _p4(price)
    assert len(m) == 35
    return m

def msg_trade(locate, ts, ref, side, shares, stock, price, match):
    m = struct.pack('>cHH', b'P', locate, 0) + _ts(ts)
    m += struct.pack('>Q', ref) + side.encode() + struct.pack('>I', shares)
    m += _stk(stock) + _p4(price) + struct.pack('>Q', match)
    assert len(m) == 44
    return m

def msg_cross_trade(locate, ts, shares, stock, price, match, cross_type):
    m = struct.pack('>cHH', b'Q', locate, 0) + _ts(ts)
    m += struct.pack('>Q', shares) + _stk(stock) + _p4(price)
    m += struct.pack('>Q', match) + cross_type.encode()
    assert len(m) == 40
    return m

def msg_broken_trade(locate, ts, match):
    m = struct.pack('>cHH', b'B', locate, 0) + _ts(ts)
    m += struct.pack('>Q', match)
    assert len(m) == 19
    return m

def msg_reg_sho(locate, ts, stock, action='0'):
    m = struct.pack('>cHH', b'Y', locate, 0) + _ts(ts)
    m += _stk(stock) + action.encode()
    assert len(m) == 20
    return m

def msg_market_participant(locate, ts, mpid, stock, primary='N', mode='N', state='A'):
    m = struct.pack('>cHH', b'L', locate, 0) + _ts(ts)
    m += mpid.ljust(4).encode('ascii') + _stk(stock)
    m += primary.encode() + mode.encode() + state.encode()
    assert len(m) == 26
    return m

def msg_mwcb_decline(ts, l1, l2, l3):
    m = struct.pack('>cHH', b'V', 0, 0) + _ts(ts)
    m += _p8(l1) + _p8(l2) + _p8(l3)
    assert len(m) == 35
    return m

def msg_mwcb_status(ts, level):
    m = struct.pack('>cHH', b'W', 0, 0) + _ts(ts)
    m += level.encode()
    assert len(m) == 12
    return m

def msg_ipo_quoting(locate, ts, stock, rel_time, qualifier='A', price=0.0):
    m = struct.pack('>cHH', b'K', locate, 0) + _ts(ts)
    m += _stk(stock) + struct.pack('>I', rel_time) + qualifier.encode() + _p4(price)
    assert len(m) == 28
    return m

def msg_luld(locate, ts, stock, ref_price, upper, lower, ext=0):
    m = struct.pack('>cHH', b'J', locate, 0) + _ts(ts)
    m += _stk(stock) + _p4(ref_price) + _p4(upper) + _p4(lower) + struct.pack('>I', ext)
    assert len(m) == 35
    return m

def msg_operational_halt(locate, ts, stock, market='Q', action='T'):
    m = struct.pack('>cHH', b'h', locate, 0) + _ts(ts)
    m += _stk(stock) + market.encode() + action.encode()
    assert len(m) == 21
    return m

def msg_rpii(locate, ts, stock, interest='N'):
    m = struct.pack('>cHH', b'N', locate, 0) + _ts(ts)
    m += _stk(stock) + interest.encode()
    assert len(m) == 20
    return m

def msg_noii(locate, ts, paired, imbalance, direction, stock,
             far_p, near_p, curr_ref, cross_type, variation):
    m = struct.pack('>cHH', b'I', locate, 0) + _ts(ts)
    m += struct.pack('>Q', paired) + struct.pack('>Q', imbalance)
    m += direction.encode() + _stk(stock)
    m += _p4(far_p) + _p4(near_p) + _p4(curr_ref)
    m += cross_type.encode() + variation.encode()
    assert len(m) == 50
    return m

def msg_dlcr(locate, ts, stock, elig='N', min_p=0, max_p=0, near_p=0,
             near_t=0, lower=0, upper=0):
    m = struct.pack('>cHH', b'O', locate, 0) + _ts(ts)
    m += _stk(stock) + elig.encode()
    m += _p4(min_p) + _p4(max_p) + _p4(near_p)
    m += struct.pack('>Q', near_t) + _p4(lower) + _p4(upper)
    assert len(m) == 48
    return m


# ===== MoldUDP64 Packet Builders =====

def build_moldudp64_packet(session_id, seq_num, messages=None,
                           heartbeat=False, end_session=False):
    """Build a MoldUDP64 downstream packet.

    session_id: string, padded/truncated to 10 bytes
    seq_num: uint64 sequence number
    messages: list of bytes (ITCH messages) for normal data packets
    heartbeat: if True, build heartbeat packet (count=0)
    end_session: if True, build end-of-session packet (count=0xFFFF)
    """
    buf = session_id.encode('ascii').ljust(10)[:10]
    buf += struct.pack('>Q', seq_num)

    if heartbeat:
        buf += struct.pack('>H', 0)
    elif end_session:
        buf += struct.pack('>H', 0xFFFF)
    else:
        buf += struct.pack('>H', len(messages))
        for msg in messages:
            buf += struct.pack('>H', len(msg)) + msg

    return buf


# ===== PCAP File Builders =====

PCAP_MAGIC_LE = 0xa1b2c3d4
PCAP_LINKTYPE_ETHERNET = 1
MOLD_DST_PORT = 26400


def _pcap_global_header():
    """24-byte libpcap global header (little-endian, microsecond resolution)."""
    return struct.pack('<IHHiIII',
                       PCAP_MAGIC_LE, 2, 4,
                       0, 0,
                       65535,
                       PCAP_LINKTYPE_ETHERNET)


def _pcap_record(ts_sec, ts_usec, frame_data):
    """16-byte pcap record header + frame data."""
    return struct.pack('<IIII',
                       ts_sec, ts_usec,
                       len(frame_data), len(frame_data)) + frame_data


def _build_udp_frame(payload, dst_port=MOLD_DST_PORT, src_port=12345,
                     src_ip='10.0.0.1', dst_ip='233.54.12.1'):
    """Ethernet + IPv4 + UDP frame wrapping the given payload."""
    # Ethernet header (14 bytes)
    eth = b'\x01\x00\x5e\x36\x0c\x01'   # dst MAC (multicast)
    eth += b'\x00\x1a\x2b\x3c\x4d\x5e'  # src MAC
    eth += struct.pack('>H', 0x0800)      # EtherType: IPv4

    # IPv4 header (20 bytes, no options)
    udp_len = 8 + len(payload)
    ip_total = 20 + udp_len
    ip_hdr = struct.pack('>BBHHHBBH',
                         0x45, 0x00,
                         ip_total,
                         0, 0x4000,
                         64, 17,
                         0)
    ip_hdr += bytes(int(x) for x in src_ip.split('.'))
    ip_hdr += bytes(int(x) for x in dst_ip.split('.'))

    # UDP header (8 bytes)
    udp_hdr = struct.pack('>HHHH', src_port, dst_port, udp_len, 0)

    return eth + ip_hdr + udp_hdr + payload


def _build_arp_frame():
    """ARP request frame (noise traffic)."""
    eth = b'\xff\xff\xff\xff\xff\xff'
    eth += b'\x00\x1a\x2b\x3c\x4d\x5e'
    eth += struct.pack('>H', 0x0806)
    arp = struct.pack('>HHBBH', 1, 0x0800, 6, 4, 1)
    arp += b'\x00\x1a\x2b\x3c\x4d\x5e' + b'\x0a\x00\x00\x01'
    arp += b'\x00\x00\x00\x00\x00\x00' + b'\x0a\x00\x00\x02'
    return eth + arp


def _build_wrong_port_udp_frame():
    """UDP frame on a non-MoldUDP64 port (noise traffic)."""
    return _build_udp_frame(b'\x00' * 24, dst_port=9999)


def build_pcap_capture(mold_packets, noise_indices=None):
    """Build a PCAP file from MoldUDP64 packets with optional noise traffic.

    noise_indices: set of packet indices before which ARP + wrong-port UDP noise
                   packets are inserted.
    """
    if noise_indices is None:
        noise_indices = set()

    pcap = _pcap_global_header()
    ts_sec = 34200
    usec = 0

    for i, pkt in enumerate(mold_packets):
        if i in noise_indices:
            pcap += _pcap_record(ts_sec, usec, _build_arp_frame())
            usec += 100
            pcap += _pcap_record(ts_sec, usec, _build_wrong_port_udp_frame())
            usec += 100

        frame = _build_udp_frame(pkt)
        pcap += _pcap_record(ts_sec, usec, frame)
        usec += 1000

    return pcap


def run_engine(captures_dir, queries):
    """Run the feed engine and return parsed JSON output."""
    queries_path = os.path.join(captures_dir, '..', 'queries.json')
    with open(queries_path, 'w') as f:
        json.dump(queries, f)

    result = subprocess.run(
        ['/app/feed_engine', captures_dir, queries_path],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Engine exited with code {result.returncode}.\n"
        f"stderr: {result.stderr[:2000]}\nstdout: {result.stdout[:500]}"
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"Engine output is not valid JSON: {e}\n"
            f"Output: {result.stdout[:1000]}"
        )
    return output


# ===================================================================
# Test 1: Full Order Book Scenario with PCAP + MoldUDP64 Transport
# ===================================================================
# Session: MKTDATA_01
# Symbols: AAPL (loc=1), MSFT (loc=2), GOOG (loc=3)
#
# PCAP features exercised:
#   - Ethernet/IP/UDP framing with correct port filtering
#   - ARP noise packets interleaved (must be ignored)
#   - Wrong-port UDP noise packets (must be ignored)
#
# MoldUDP64 features exercised:
#   - Multi-message packets (1-4 messages per packet)
#   - Heartbeat packets (2x)
#   - Sequence gap (seq 16-17 missing, admin messages lost)
#   - End-of-session marker
#   - Sequence number tracking across packets
#
# Order book features exercised:
#   - Add(A/F), Execute(E), ExecutePrice(C), Cancel(X),
#     Delete(D), Replace(U), Trade(P), CrossTrade(Q), BrokenTrade(B)
#   - Cumulative cancel (two X msgs on same order)
#   - Replace inherits side/symbol/MPID
#   - Non-printable execution excluded from VWAP
#   - Broken trade reverses MSFT execution
#   - Multi-level BBO aggregation
#   - Replace on partially-executed order
# ===================================================================

class TestMainScenario:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        T0 = 34_200_000_000_000  # 09:30:00

        SESSION = "MKTDATA_01"

        # Build all ITCH messages in sequence
        itch_messages = [
            # 1-4: System/admin setup
            msg_system_event(0, T0, 'O'),
            msg_stock_directory(1, T0 + 1_000_000, 'AAPL'),
            msg_stock_directory(2, T0 + 2_000_000, 'MSFT'),
            msg_stock_directory(3, T0 + 3_000_000, 'GOOG'),
            # 5-7: Trading actions
            msg_trading_action(1, T0 + 10_000_000, 'AAPL'),
            msg_trading_action(2, T0 + 11_000_000, 'MSFT'),
            msg_trading_action(3, T0 + 12_000_000, 'GOOG'),
            # 8-11: AAPL order book
            msg_add_order(1, 34_201_000_000_000, 1001, 'B', 1000, 'AAPL', 150.0),
            msg_add_order(1, 34_201_001_000_000, 1002, 'B', 500, 'AAPL', 149.5),
            msg_add_order(1, 34_201_002_000_000, 1003, 'S', 800, 'AAPL', 151.0),
            msg_add_order_mpid(1, 34_201_003_000_000, 1004, 'S', 300, 'AAPL', 150.5, 'GSCO'),
            # 12-13: MSFT order book
            msg_add_order(2, 34_202_000_000_000, 2001, 'B', 600, 'MSFT', 300.0),
            msg_add_order(2, 34_202_001_000_000, 2002, 'S', 400, 'MSFT', 301.0),
            # 14-15: Executions
            msg_order_executed(1, 34_203_000_000_000, 1003, 200, 5001),  # AAPL S 800->600
            msg_order_executed(2, 34_203_001_000_000, 2001, 400, 5002),  # MSFT B 600->200
            # [16-17: GAP - these admin messages are "lost" in transit]
            # msg_reg_sho(1, 34_203_500_000_000, 'AAPL'),
            # msg_market_participant(1, 34_203_600_000_000, 'GSCO', 'AAPL'),
            # 18-19: Cumulative cancels
            msg_order_cancel(1, 34_204_000_000_000, 1002, 200),  # AAPL B 500->300
            msg_order_cancel(1, 34_204_001_000_000, 1002, 100),  # AAPL B 300->200
            # 20: Replace (inherits side=S, symbol=AAPL, MPID=GSCO)
            msg_order_replace(1, 34_205_000_000_000, 1004, 1005, 500, 150.75),
            # 21: Non-displayable trade
            msg_trade(2, 34_206_000_000_000, 0, 'B', 200, 'MSFT', 300.5, 5003),
            # 22: Cross trade
            msg_cross_trade(3, 34_207_000_000_000, 10000, 'GOOG', 2800.0, 5004, 'O'),
            # 23: Executed with price (printable)
            msg_order_executed_price(1, 34_208_000_000_000, 1001, 300, 5005, 'Y', 150.25),
            # 24: Broken trade (reverses MSFT match 5002)
            msg_broken_trade(2, 34_209_000_000_000, 5002),
            # 25-26: GOOG orders
            msg_add_order(3, 34_210_000_000_000, 3001, 'B', 200, 'GOOG', 2799.0),
            msg_add_order(3, 34_210_001_000_000, 3002, 'S', 150, 'GOOG', 2801.0),
            # 27: Delete
            msg_order_delete(1, 34_211_000_000_000, 1002),
            # 28: Non-printable execution (excluded from VWAP)
            msg_order_executed_price(1, 34_212_000_000_000, 1003, 100, 5006, 'N', 150.8),
            # 29-30: More AAPL orders at existing levels
            msg_add_order(1, 34_213_000_000_000, 1006, 'B', 300, 'AAPL', 150.0),
            msg_add_order(1, 34_213_001_000_000, 1007, 'S', 200, 'AAPL', 150.75),
            # 31: Another execution
            msg_order_executed(1, 34_214_000_000_000, 1005, 100, 5007),  # AAPL S 500->400
            # 32: Replace on partially-executed order
            msg_order_replace(1, 34_215_000_000_000, 1001, 1008, 400, 150.2),
            # 33: End of day
            msg_system_event(0, 34_216_000_000_000, 'C'),
        ]

        packets = [
            # PKT 1: seq=1, 4 msgs (system event, 3 stock directories)
            build_moldudp64_packet(SESSION, 1, itch_messages[0:4]),
            # PKT 2: seq=5, 3 msgs (trading actions)
            build_moldudp64_packet(SESSION, 5, itch_messages[4:7]),
            # PKT 3: seq=8, 4 msgs (AAPL orders)
            build_moldudp64_packet(SESSION, 8, itch_messages[7:11]),
            # PKT 4: seq=12, 2 msgs (MSFT orders)
            build_moldudp64_packet(SESSION, 12, itch_messages[11:13]),
            # Heartbeat: seq=14
            build_moldudp64_packet(SESSION, 14, heartbeat=True),
            # PKT 5: seq=14, 2 msgs (executions)
            build_moldudp64_packet(SESSION, 14, itch_messages[13:15]),
            # *** GAP: seq 16-17 missing (2 admin messages lost) ***
            # PKT 6: seq=18, 2 msgs (cumulative cancels)
            build_moldudp64_packet(SESSION, 18, itch_messages[15:17]),
            # PKT 7: seq=20, 1 msg (replace)
            build_moldudp64_packet(SESSION, 20, itch_messages[17:18]),
            # PKT 8: seq=21, 1 msg (trade)
            build_moldudp64_packet(SESSION, 21, itch_messages[18:19]),
            # PKT 9: seq=22, 1 msg (cross trade)
            build_moldudp64_packet(SESSION, 22, itch_messages[19:20]),
            # PKT 10: seq=23, 1 msg (exec w/price printable)
            build_moldudp64_packet(SESSION, 23, itch_messages[20:21]),
            # PKT 11: seq=24, 1 msg (broken trade)
            build_moldudp64_packet(SESSION, 24, itch_messages[21:22]),
            # Heartbeat: seq=25
            build_moldudp64_packet(SESSION, 25, heartbeat=True),
            # PKT 12: seq=25, 2 msgs (GOOG orders)
            build_moldudp64_packet(SESSION, 25, itch_messages[22:24]),
            # PKT 13: seq=27, 1 msg (delete)
            build_moldudp64_packet(SESSION, 27, itch_messages[24:25]),
            # PKT 14: seq=28, 1 msg (exec w/price non-printable)
            build_moldudp64_packet(SESSION, 28, itch_messages[25:26]),
            # PKT 15: seq=29, 2 msgs (more AAPL orders)
            build_moldudp64_packet(SESSION, 29, itch_messages[26:28]),
            # PKT 16: seq=31, 1 msg (execution)
            build_moldudp64_packet(SESSION, 31, itch_messages[28:29]),
            # PKT 17: seq=32, 1 msg (replace)
            build_moldudp64_packet(SESSION, 32, itch_messages[29:30]),
            # PKT 18: seq=33, 1 msg (system event end)
            build_moldudp64_packet(SESSION, 33, itch_messages[30:31]),
            # End of session
            build_moldudp64_packet(SESSION, 34, end_session=True),
        ]

        captures_dir = str(tmp_path / 'captures')
        os.makedirs(captures_dir)
        # Noise at packet indices 0, 5, 10, 15 — ARP + wrong-port UDP
        with open(os.path.join(captures_dir, 'channel_a.pcap'), 'wb') as f:
            f.write(build_pcap_capture(packets, noise_indices={0, 5, 10, 15}))

        queries = {
            "bbo_queries": [
                {"symbol": "AAPL", "timestamp_ns": 34_201_004_000_000},   # Q0
                {"symbol": "AAPL", "timestamp_ns": 34_205_001_000_000},   # Q1
                {"symbol": "AAPL", "timestamp_ns": 34_212_001_000_000},   # Q2
                {"symbol": "MSFT", "timestamp_ns": 34_212_001_000_000},   # Q3
                {"symbol": "GOOG", "timestamp_ns": 34_212_001_000_000},   # Q4
                {"symbol": "AAPL", "timestamp_ns": 34_213_002_000_000},   # Q5
                {"symbol": "AAPL", "timestamp_ns": 34_215_001_000_000},   # Q6
            ]
        }

        self.output = run_engine(captures_dir, queries)

    # ----- VWAP tests -----
    def test_aapl_vwap(self):
        # match 5001: 200 @ 151.0 (E, printable)
        # match 5005: 300 @ 150.25 (C, printable=Y)
        # match 5006: 100 @ 150.8 (C, printable=N, EXCLUDED)
        # match 5007: 100 @ 150.75 (E, printable)
        expected = (200 * 151.0 + 300 * 150.25 + 100 * 150.75) / 600.0
        assert self.output['vwap']['AAPL'] == pytest.approx(expected, abs=0.001)

    def test_msft_vwap(self):
        # match 5002: 400 @ 300.0 (E) -> BROKEN
        # match 5003: 200 @ 300.5 (P, printable)
        assert self.output['vwap']['MSFT'] == pytest.approx(300.5, abs=0.001)

    def test_goog_vwap(self):
        # match 5004: 10000 @ 2800.0 (Q, printable)
        assert self.output['vwap']['GOOG'] == pytest.approx(2800.0, abs=0.001)

    # ----- Volume tests -----
    def test_aapl_volume(self):
        assert self.output['volume']['AAPL'] == 600

    def test_msft_volume(self):
        assert self.output['volume']['MSFT'] == 200

    def test_goog_volume(self):
        assert self.output['volume']['GOOG'] == 10000

    # ----- BBO Q0: initial AAPL book -----
    def test_bbo_q0_initial_book(self):
        bbo = self.output['bbo'][0]
        assert bbo['symbol'] == 'AAPL'
        assert bbo['bid_price'] == pytest.approx(150.0, abs=0.0001)
        assert bbo['bid_size'] == 1000
        assert bbo['ask_price'] == pytest.approx(150.5, abs=0.0001)
        assert bbo['ask_size'] == 300

    # ----- BBO Q1: after replace -----
    def test_bbo_q1_after_replace(self):
        bbo = self.output['bbo'][1]
        assert bbo['bid_price'] == pytest.approx(150.0, abs=0.0001)
        assert bbo['bid_size'] == 1000
        assert bbo['ask_price'] == pytest.approx(150.75, abs=0.0001)
        assert bbo['ask_size'] == 500

    # ----- BBO Q2: AAPL after executions and delete -----
    def test_bbo_q2_aapl_mid(self):
        bbo = self.output['bbo'][2]
        assert bbo['bid_price'] == pytest.approx(150.0, abs=0.0001)
        assert bbo['bid_size'] == 700
        assert bbo['ask_price'] == pytest.approx(150.75, abs=0.0001)
        assert bbo['ask_size'] == 500

    # ----- BBO Q3: MSFT state -----
    def test_bbo_q3_msft(self):
        bbo = self.output['bbo'][3]
        assert bbo['bid_price'] == pytest.approx(300.0, abs=0.0001)
        assert bbo['bid_size'] == 200
        assert bbo['ask_price'] == pytest.approx(301.0, abs=0.0001)
        assert bbo['ask_size'] == 400

    # ----- BBO Q4: GOOG state -----
    def test_bbo_q4_goog(self):
        bbo = self.output['bbo'][4]
        assert bbo['bid_price'] == pytest.approx(2799.0, abs=0.0001)
        assert bbo['bid_size'] == 200
        assert bbo['ask_price'] == pytest.approx(2801.0, abs=0.0001)
        assert bbo['ask_size'] == 150

    # ----- BBO Q5: multi-level aggregation -----
    def test_bbo_q5_aggregation(self):
        bbo = self.output['bbo'][5]
        assert bbo['bid_price'] == pytest.approx(150.0, abs=0.0001)
        assert bbo['bid_size'] == 1000   # 700 + 300 at 150.0
        assert bbo['ask_price'] == pytest.approx(150.75, abs=0.0001)
        assert bbo['ask_size'] == 700    # 500 + 200 at 150.75

    # ----- BBO Q6: after second replace -----
    def test_bbo_q6_after_second_replace(self):
        bbo = self.output['bbo'][6]
        assert bbo['bid_price'] == pytest.approx(150.2, abs=0.0001)
        assert bbo['bid_size'] == 400
        assert bbo['ask_price'] == pytest.approx(150.75, abs=0.0001)
        assert bbo['ask_size'] == 600    # 400 + 200 at 150.75

    # ----- Diagnostics tests -----
    def test_diag_sessions(self):
        assert self.output['diagnostics']['sessions'] == ['MKTDATA_01']

    def test_diag_total_messages(self):
        assert self.output['diagnostics']['total_messages'] == 31

    def test_diag_gaps(self):
        gaps = self.output['diagnostics']['gaps']
        assert len(gaps) == 1
        assert gaps[0]['session'] == 'MKTDATA_01'
        assert gaps[0]['expected_seq'] == 16
        assert gaps[0]['actual_seq'] == 18

    def test_diag_heartbeat_count(self):
        assert self.output['diagnostics']['heartbeat_count'] == 2


# ===================================================================
# Test 2: Edge Cases with All 23 Message Types
# ===================================================================
# Session: EDGETEST_1
# Symbols: NVDA (loc=4), AMD (loc=5)
#
# PCAP features:
#   - Noise packets at specific positions
#
# MoldUDP64 features:
#   - Multi-message packets (up to 5 per packet)
#   - 1 heartbeat
#   - 1 gap (seq 28 lost = DLCR message)
#   - End-of-session marker
#
# Order book edge cases:
#   - All 23 message types parsed without crash
#   - Order executing to exactly zero shares
#   - BBO with empty bid side (ask only)
#   - BBO with empty ask side (bid only)
#   - BBO with completely empty book
#   - Operations on nonexistent order references
#   - Cancel + Execute to zero
#   - Chain of two consecutive replaces
#   - Broken trade on fully-removed order
# ===================================================================

class TestEdgeCases:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        T0 = 36_000_000_000_000  # 10:00:00

        SESSION = "EDGETEST_1"

        itch_messages = [
            # 1-5: System setup and stock directories
            msg_system_event(0, T0, 'O'),
            msg_stock_directory(4, T0 + 1_000_000, 'NVDA'),
            msg_stock_directory(5, T0 + 2_000_000, 'AMD'),
            msg_trading_action(4, T0 + 10_000_000, 'NVDA'),
            msg_trading_action(5, T0 + 11_000_000, 'AMD'),
            # 6-9: Administrative messages (must not crash)
            msg_reg_sho(4, T0 + 20_000_000, 'NVDA', '0'),
            msg_market_participant(4, T0 + 21_000_000, 'GSCO', 'NVDA', 'Y', 'N', 'A'),
            msg_mwcb_decline(T0 + 22_000_000, 27000.0, 18000.0, 12000.0),
            msg_mwcb_status(T0 + 23_000_000, '1'),
            # 10-14: More admin messages
            msg_ipo_quoting(4, T0 + 24_000_000, 'NVDA', 36000, 'A', 100.0),
            msg_luld(4, T0 + 25_000_000, 'NVDA', 100.0, 110.0, 90.0),
            msg_operational_halt(4, T0 + 26_000_000, 'NVDA'),
            msg_rpii(4, T0 + 27_000_000, 'NVDA', 'A'),
            msg_noii(4, T0 + 28_000_000, 1000, 500, 'B', 'NVDA',
                     100.0, 100.5, 100.25, 'O', 'L'),
            # 15-16: Order executes to exactly zero -> removed
            msg_add_order(4, 36_001_000_000_000, 4001, 'B', 100, 'NVDA', 50.0),
            msg_order_executed(4, 36_001_100_000_000, 4001, 100, 6001),
            # 17-19: Partial exec then replace
            msg_add_order(4, 36_002_000_000_000, 4002, 'B', 200, 'NVDA', 50.0),
            msg_order_executed(4, 36_002_100_000_000, 4002, 100, 6002),  # 200->100
            msg_order_replace(4, 36_003_000_000_000, 4002, 4003, 300, 50.5),
            # 20: Break trade on fully-removed order
            msg_broken_trade(4, 36_004_000_000_000, 6001),
            # 21: AMD: sell only (no bids)
            msg_add_order(5, 36_005_000_000_000, 5001, 'S', 150, 'AMD', 51.0),
            # 22-24: Graceful handling: ops on nonexistent refs
            msg_order_cancel(4, 36_006_000_000_000, 9999, 100),
            msg_order_delete(4, 36_006_001_000_000, 9998),
            msg_order_executed(4, 36_006_002_000_000, 9997, 50, 6003),
            # 25-27: Cancel then execute to zero
            msg_add_order(4, 36_007_000_000_000, 4004, 'S', 500, 'NVDA', 52.0),
            msg_order_cancel(4, 36_007_100_000_000, 4004, 200),         # 500->300
            msg_order_executed(4, 36_007_200_000_000, 4004, 300, 6004), # 300->0
            # [28: GAP - DLCR message lost]
            # msg_dlcr(4, 36_008_000_000_000, 'NVDA'),
            # 29-31: Chain of two replaces
            msg_add_order(4, 36_009_000_000_000, 4005, 'B', 100, 'NVDA', 48.0),
            msg_order_replace(4, 36_009_100_000_000, 4005, 4006, 150, 48.5),
            msg_order_replace(4, 36_009_200_000_000, 4006, 4007, 200, 49.0),
            # 32: End of day
            msg_system_event(0, 36_010_000_000_000, 'C'),
        ]

        packets = [
            # PKT 1: seq=1, 5 msgs (system, stock dirs, trading actions)
            build_moldudp64_packet(SESSION, 1, itch_messages[0:5]),
            # PKT 2: seq=6, 4 msgs (admin: RegSHO, MktPart, MWCB x2)
            build_moldudp64_packet(SESSION, 6, itch_messages[5:9]),
            # PKT 3: seq=10, 5 msgs (admin: IPO, LULD, OpHalt, RPII, NOII)
            build_moldudp64_packet(SESSION, 10, itch_messages[9:14]),
            # PKT 4: seq=15, 2 msgs (add 4001, exec 4001 to zero)
            build_moldudp64_packet(SESSION, 15, itch_messages[14:16]),
            # Heartbeat: seq=17
            build_moldudp64_packet(SESSION, 17, heartbeat=True),
            # PKT 5: seq=17, 3 msgs (add 4002, exec 4002, replace 4002->4003)
            build_moldudp64_packet(SESSION, 17, itch_messages[16:19]),
            # PKT 6: seq=20, 2 msgs (broken trade, add AMD)
            build_moldudp64_packet(SESSION, 20, itch_messages[19:21]),
            # PKT 7: seq=22, 3 msgs (ops on nonexistent refs)
            build_moldudp64_packet(SESSION, 22, itch_messages[21:24]),
            # PKT 8: seq=25, 3 msgs (add 4004, cancel, exec to zero)
            build_moldudp64_packet(SESSION, 25, itch_messages[24:27]),
            # *** GAP: seq 28 missing (DLCR message lost) ***
            # PKT 9: seq=29, 3 msgs (add 4005, replace->4006, replace->4007)
            build_moldudp64_packet(SESSION, 29, itch_messages[27:30]),
            # PKT 10: seq=32, 1 msg (system event end)
            build_moldudp64_packet(SESSION, 32, itch_messages[30:31]),
            # End of session
            build_moldudp64_packet(SESSION, 33, end_session=True),
        ]

        captures_dir = str(tmp_path / 'captures')
        os.makedirs(captures_dir)
        # Noise at packet indices 2, 7
        with open(os.path.join(captures_dir, 'edge_feed.pcap'), 'wb') as f:
            f.write(build_pcap_capture(packets, noise_indices={2, 7}))

        queries = {
            "bbo_queries": [
                {"symbol": "NVDA", "timestamp_ns": 36_001_200_000_000},  # Q0
                {"symbol": "NVDA", "timestamp_ns": 36_003_100_000_000},  # Q1
                {"symbol": "AMD",  "timestamp_ns": 36_005_100_000_000},  # Q2
                {"symbol": "NVDA", "timestamp_ns": 36_007_300_000_000},  # Q3
                {"symbol": "NVDA", "timestamp_ns": 36_009_300_000_000},  # Q4
            ]
        }

        self.output = run_engine(captures_dir, queries)

    # ----- VWAP tests -----
    def test_nvda_vwap(self):
        # 6001: 100@50 -> BROKEN
        # 6002: 100@50 -> OK
        # 6003: nonexistent ref -> not recorded
        # 6004: 300@52 -> OK
        expected = (100 * 50.0 + 300 * 52.0) / 400.0  # 51.5
        assert self.output['vwap']['NVDA'] == pytest.approx(expected, abs=0.001)

    def test_nvda_volume(self):
        assert self.output['volume']['NVDA'] == 400

    def test_amd_not_in_vwap(self):
        assert 'AMD' not in self.output.get('vwap', {})

    def test_amd_not_in_volume(self):
        assert 'AMD' not in self.output.get('volume', {})

    # ----- BBO Q0: empty book after order executed to zero -----
    def test_bbo_q0_empty(self):
        bbo = self.output['bbo'][0]
        assert bbo['symbol'] == 'NVDA'
        assert bbo['bid_price'] is None
        assert bbo['bid_size'] == 0
        assert bbo['ask_price'] is None
        assert bbo['ask_size'] == 0

    # ----- BBO Q1: bid only (no asks) -----
    def test_bbo_q1_bid_only(self):
        bbo = self.output['bbo'][1]
        assert bbo['bid_price'] == pytest.approx(50.5, abs=0.0001)
        assert bbo['bid_size'] == 300
        assert bbo['ask_price'] is None
        assert bbo['ask_size'] == 0

    # ----- BBO Q2: ask only (no bids) -----
    def test_bbo_q2_ask_only(self):
        bbo = self.output['bbo'][2]
        assert bbo['symbol'] == 'AMD'
        assert bbo['bid_price'] is None
        assert bbo['bid_size'] == 0
        assert bbo['ask_price'] == pytest.approx(51.0, abs=0.0001)
        assert bbo['ask_size'] == 150

    # ----- BBO Q3: after cancel+execute to zero removes sell -----
    def test_bbo_q3_sell_removed(self):
        bbo = self.output['bbo'][3]
        assert bbo['bid_price'] == pytest.approx(50.5, abs=0.0001)
        assert bbo['bid_size'] == 300
        assert bbo['ask_price'] is None
        assert bbo['ask_size'] == 0

    # ----- BBO Q4: chain replace, best bid is still 4003 -----
    def test_bbo_q4_chain_replace(self):
        bbo = self.output['bbo'][4]
        assert bbo['bid_price'] == pytest.approx(50.5, abs=0.0001)
        assert bbo['bid_size'] == 300
        assert bbo['ask_price'] is None
        assert bbo['ask_size'] == 0

    # ----- Diagnostics tests -----
    def test_diag_sessions(self):
        assert self.output['diagnostics']['sessions'] == ['EDGETEST_1']

    def test_diag_total_messages(self):
        assert self.output['diagnostics']['total_messages'] == 31

    def test_diag_gaps(self):
        gaps = self.output['diagnostics']['gaps']
        assert len(gaps) == 1
        assert gaps[0]['session'] == 'EDGETEST_1'
        assert gaps[0]['expected_seq'] == 28
        assert gaps[0]['actual_seq'] == 29

    def test_diag_heartbeat_count(self):
        assert self.output['diagnostics']['heartbeat_count'] == 1


# ===================================================================
# Test 3: Multi-Capture File / Multi-Session Merge
# ===================================================================
# Two PCAP capture files from different sessions with interleaved timestamps.
# File 1: Session "ALPHA_FEED" with TSLA orders (noise at start)
# File 2: Session "BETA_FEED" with META orders (has a gap, noise interleaved)
#
# Tests:
#   - Reading multiple .pcap files from captures directory
#   - Cross-session timestamp merge for BBO queries
#   - Aggregated diagnostics across sessions
#   - PCAP noise filtering across multiple files
# ===================================================================

class TestMultiCapture:

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        T0 = 34_200_000_000_000  # 09:30:00

        # === File 1: ALPHA_FEED ===
        alpha_msgs = [
            msg_system_event(0, T0, 'O'),
            msg_stock_directory(6, T0 + 1_000_000, 'TSLA'),
            msg_trading_action(6, T0 + 10_000_000, 'TSLA'),
            msg_add_order(6, T0 + 100_000_000, 7001, 'B', 100, 'TSLA', 200.0),
            msg_add_order(6, T0 + 101_000_000, 7002, 'S', 50, 'TSLA', 201.0),
            msg_order_executed(6, T0 + 200_000_000, 7001, 50, 9001),  # TSLA B 100->50
        ]

        alpha_packets = [
            build_moldudp64_packet("ALPHA_FEED", 1, alpha_msgs[0:3]),
            build_moldudp64_packet("ALPHA_FEED", 4, alpha_msgs[3:5]),
            build_moldudp64_packet("ALPHA_FEED", 6, heartbeat=True),
            build_moldudp64_packet("ALPHA_FEED", 6, alpha_msgs[5:6]),
            build_moldudp64_packet("ALPHA_FEED", 7, end_session=True),
        ]

        # === File 2: BETA_FEED (with gap) ===
        beta_msgs = [
            msg_system_event(0, T0 + 50_000_000, 'O'),
            msg_stock_directory(7, T0 + 51_000_000, 'META'),
            msg_trading_action(7, T0 + 60_000_000, 'META'),
            # [seq 4-5: GAP - 2 messages lost]
            msg_add_order(7, T0 + 150_000_000, 8001, 'B', 200, 'META', 450.0),
            msg_add_order(7, T0 + 151_000_000, 8002, 'S', 100, 'META', 451.0),
        ]

        beta_packets = [
            build_moldudp64_packet("BETA_FEED", 1, beta_msgs[0:3]),
            # GAP: seq 4-5 missing
            build_moldudp64_packet("BETA_FEED", 6, beta_msgs[3:5]),
            build_moldudp64_packet("BETA_FEED", 8, end_session=True),
        ]

        captures_dir = str(tmp_path / 'captures')
        os.makedirs(captures_dir)
        # Alpha: noise at start (index 0)
        with open(os.path.join(captures_dir, 'alpha.pcap'), 'wb') as f:
            f.write(build_pcap_capture(alpha_packets, noise_indices={0}))
        # Beta: noise at index 1
        with open(os.path.join(captures_dir, 'beta.pcap'), 'wb') as f:
            f.write(build_pcap_capture(beta_packets, noise_indices={1}))

        queries = {
            "bbo_queries": [
                {"symbol": "TSLA", "timestamp_ns": T0 + 201_000_000},
                {"symbol": "META", "timestamp_ns": T0 + 201_000_000},
            ]
        }

        self.output = run_engine(captures_dir, queries)

    # ----- BBO: TSLA after execution -----
    def test_bbo_tsla(self):
        bbo = self.output['bbo'][0]
        assert bbo['symbol'] == 'TSLA'
        assert bbo['bid_price'] == pytest.approx(200.0, abs=0.0001)
        assert bbo['bid_size'] == 50  # 100 - 50 executed
        assert bbo['ask_price'] == pytest.approx(201.0, abs=0.0001)
        assert bbo['ask_size'] == 50

    # ----- BBO: META from second file -----
    def test_bbo_meta(self):
        bbo = self.output['bbo'][1]
        assert bbo['symbol'] == 'META'
        assert bbo['bid_price'] == pytest.approx(450.0, abs=0.0001)
        assert bbo['bid_size'] == 200
        assert bbo['ask_price'] == pytest.approx(451.0, abs=0.0001)
        assert bbo['ask_size'] == 100

    # ----- VWAP/Volume -----
    def test_tsla_vwap(self):
        assert self.output['vwap']['TSLA'] == pytest.approx(200.0, abs=0.001)

    def test_tsla_volume(self):
        assert self.output['volume']['TSLA'] == 50

    def test_meta_not_in_vwap(self):
        assert 'META' not in self.output.get('vwap', {})

    # ----- Diagnostics: multi-session aggregation -----
    def test_diag_sessions_sorted(self):
        assert self.output['diagnostics']['sessions'] == ['ALPHA_FEED', 'BETA_FEED']

    def test_diag_total_messages(self):
        # ALPHA: 3 + 2 + 1 = 6; BETA: 3 + 2 = 5; total = 11
        assert self.output['diagnostics']['total_messages'] == 11

    def test_diag_gaps(self):
        gaps = self.output['diagnostics']['gaps']
        assert len(gaps) == 1
        assert gaps[0]['session'] == 'BETA_FEED'
        assert gaps[0]['expected_seq'] == 4
        assert gaps[0]['actual_seq'] == 6

    def test_diag_heartbeat_count(self):
        # 1 from ALPHA, 0 from BETA
        assert self.output['diagnostics']['heartbeat_count'] == 1

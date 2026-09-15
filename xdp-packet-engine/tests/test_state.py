"""Tests for the XDP-style packet transformation engine.

"""

import struct
import subprocess
import os
import pytest

PKT_ENGINE = "/app/pkt_engine"

TAG_MAGIC = 0xD9F04B21
TAG_ROT_BITS = 13
TAG_XOR_CONST = 0xCAFE1337
TAG_TRAILER_LEN = 12


# ================================================================
# Packet construction helpers
# ================================================================

def compute_checksum(data: bytes) -> int:
    """RFC 1071 one's complement checksum (big-endian computation)."""
    if len(data) % 2:
        data = data + b'\x00'
    total = 0
    for i in range(0, len(data), 2):
        total += struct.unpack('!H', data[i:i+2])[0]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def compute_tag_digest(data: bytes) -> int:
    """Compute tag digest: XOR-fold 32-bit BE words, ROL 13, XOR 0xCAFE1337."""
    fold = 0
    i = 0
    while i + 4 <= len(data):
        word = struct.unpack('!I', data[i:i+4])[0]
        fold ^= word
        i += 4
    rem = len(data) - i
    if rem > 0:
        padded = data[i:] + b'\x00' * (4 - rem)
        word = struct.unpack('!I', padded)[0]
        fold ^= word
    fold = ((fold << TAG_ROT_BITS) | (fold >> (32 - TAG_ROT_BITS))) & 0xFFFFFFFF
    fold ^= TAG_XOR_CONST
    return fold


def mac(s: str) -> bytes:
    """Parse 'aa:bb:cc:dd:ee:ff' to 6-byte MAC address."""
    return bytes(int(x, 16) for x in s.split(':'))


def ipv4_addr(s: str) -> bytes:
    """Parse '10.0.0.1' to 4-byte IPv4 address."""
    return bytes(int(x) for x in s.split('.'))


def make_eth(dst: bytes, src: bytes, ethertype: int) -> bytes:
    """Build a 14-byte Ethernet header."""
    return dst + src + struct.pack('!H', ethertype)


def make_vlan(vid: int, inner_proto: int) -> bytes:
    """Build a 4-byte 802.1Q VLAN tag (TCI + encapsulated EtherType)."""
    return struct.pack('!HH', vid & 0xFFF, inner_proto)


def make_ipv4(src: str, dst: str, ttl: int, proto: int,
              payload: bytes) -> bytes:
    """Build an IPv4 header (IHL=5, no options) + payload."""
    total_len = 20 + len(payload)
    hdr = struct.pack('!BBHHHBBH4s4s',
                      0x45, 0, total_len, 0x1234, 0x4000,
                      ttl, proto, 0,
                      ipv4_addr(src), ipv4_addr(dst))
    ck = compute_checksum(hdr)
    hdr = struct.pack('!BBHHHBBH4s4s',
                      0x45, 0, total_len, 0x1234, 0x4000,
                      ttl, proto, ck,
                      ipv4_addr(src), ipv4_addr(dst))
    return hdr + payload


def make_icmp_echo(typ: int, ident: int, seq: int, data: bytes) -> bytes:
    """Build an ICMP echo message (request or reply) with correct checksum."""
    msg = struct.pack('!BBHHH', typ, 0, 0, ident, seq) + data
    ck = compute_checksum(msg)
    return struct.pack('!BBHHH', typ, 0, ck, ident, seq) + data


def make_ipv6(src: bytes, dst: bytes, hop_limit: int,
              nexthdr: int, payload_len: int) -> bytes:
    """Build a 40-byte IPv6 header."""
    return struct.pack('!IHBB16s16s',
                       0x60000000, payload_len, nexthdr, hop_limit,
                       src, dst)


def make_icmpv6_echo(typ: int, ident: int, seq: int, data: bytes,
                     src_ip6: bytes, dst_ip6: bytes) -> bytes:
    """Build an ICMPv6 echo message with pseudo-header checksum."""
    msg = struct.pack('!BBHHH', typ, 0, 0, ident, seq) + data
    pseudo = (src_ip6 + dst_ip6 +
              struct.pack('!I', len(msg)) + b'\x00\x00\x00\x3a')
    ck = compute_checksum(pseudo + msg)
    return struct.pack('!BBHHH', typ, 0, ck, ident, seq) + data


def make_udp(src_port: int, dst_port: int, data: bytes) -> bytes:
    """Build a UDP header + payload (checksum=0, optional for IPv4)."""
    length = 8 + len(data)
    return struct.pack('!HHHH', src_port, dst_port, length, 0) + data


def make_tag_trailer(key: int, l3_proto: int, digest: int) -> bytes:
    """Build a 12-byte tag trailer."""
    return struct.pack('!IHHI', TAG_MAGIC, key, l3_proto, digest)


def run_engine(hex_input: str, *ops) -> str:
    """Run pkt_engine with the given pipeline and return stripped stdout."""
    args = [PKT_ENGINE]
    for op in ops:
        args.extend(op.split())
    if not hex_input.endswith('\n'):
        hex_input += '\n'
    result = subprocess.run(args, input=hex_input,
                            capture_output=True, text=True, timeout=10)
    return result.stdout.strip()


# ================================================================
# Fixture: compile the engine once
# ================================================================

@pytest.fixture(scope="session", autouse=True)
def build_engine():
    result = subprocess.run(["make", "-C", "/app"],
                            capture_output=True, text=True)
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"
    assert os.path.isfile(PKT_ENGINE), "pkt_engine binary not found"


# ================================================================
# Reusable packet components
# ================================================================

DST = mac('aa:bb:cc:dd:ee:ff')
SRC = mac('11:22:33:44:55:66')
ICMP_DATA = b'\x41' * 8
ICMP_REQ = make_icmp_echo(8, 0x1234, 1, ICMP_DATA)
ICMP_REPLY = make_icmp_echo(0, 0x1234, 1, ICMP_DATA)

IPV6_SRC = b'\xfd\x00' + b'\x00' * 13 + b'\x01'   # fd00::1
IPV6_DST = b'\xfd\x00' + b'\x00' * 13 + b'\x02'   # fd00::2
ICMPV6_DATA = b'\x42' * 8


# ================================================================
# Tests — standard operations
# ================================================================

class TestVlanPop:
    def test_basic(self):
        """Remove a single 802.1Q VLAN tag."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x8100) + make_vlan(42, 0x0800) + ip
        pkt_exp = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'vlan-pop') == pkt_exp.hex()

    def test_qinq_removes_outer(self):
        """Remove outer 802.1ad tag from a Q-in-Q frame, inner 802.1Q remains."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = (make_eth(DST, SRC, 0x88A8) +
                  make_vlan(100, 0x8100) +
                  make_vlan(200, 0x0800) + ip)
        pkt_exp = (make_eth(DST, SRC, 0x8100) +
                   make_vlan(200, 0x0800) + ip)
        assert run_engine(pkt_in.hex(), 'vlan-pop') == pkt_exp.hex()

    def test_no_vlan_drops(self):
        """Attempting vlan-pop on an untagged frame should drop (no output)."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'vlan-pop') == ''


class TestVlanPush:
    def test_basic(self):
        """Insert a single 802.1Q VLAN tag."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        pkt_exp = make_eth(DST, SRC, 0x8100) + make_vlan(42, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'vlan-push 42') == pkt_exp.hex()

    def test_roundtrip(self):
        """Push then pop should produce the original packet."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'vlan-push 99', 'vlan-pop') == pkt_in.hex()


class TestEchoReply:
    def test_ipv4_icmp(self):
        """Convert IPv4 ICMP Echo Request to Reply: swap addrs, fix checksum."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip

        ip_reply = make_ipv4('10.0.0.2', '10.0.0.1', 64, 1, ICMP_REPLY)
        pkt_exp = make_eth(SRC, DST, 0x0800) + ip_reply

        assert run_engine(pkt_in.hex(), 'echo-reply') == pkt_exp.hex()

    def test_ipv6_icmpv6(self):
        """Convert IPv6 ICMPv6 Echo Request to Reply with pseudo-header checksum."""
        icmpv6_req = make_icmpv6_echo(128, 0x5678, 1, ICMPV6_DATA,
                                      IPV6_SRC, IPV6_DST)
        ip6 = make_ipv6(IPV6_SRC, IPV6_DST, 64, 58, len(icmpv6_req))
        pkt_in = make_eth(DST, SRC, 0x86DD) + ip6 + icmpv6_req

        icmpv6_rep = make_icmpv6_echo(129, 0x5678, 1, ICMPV6_DATA,
                                      IPV6_DST, IPV6_SRC)
        ip6_rep = make_ipv6(IPV6_DST, IPV6_SRC, 64, 58, len(icmpv6_rep))
        pkt_exp = make_eth(SRC, DST, 0x86DD) + ip6_rep + icmpv6_rep

        assert run_engine(pkt_in.hex(), 'echo-reply') == pkt_exp.hex()

    def test_vlan_tagged(self):
        """Echo reply on a VLAN-tagged packet should preserve the VLAN tag."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x8100) + make_vlan(77, 0x0800) + ip

        ip_reply = make_ipv4('10.0.0.2', '10.0.0.1', 64, 1, ICMP_REPLY)
        pkt_exp = (make_eth(SRC, DST, 0x8100) +
                   make_vlan(77, 0x0800) + ip_reply)

        assert run_engine(pkt_in.hex(), 'echo-reply') == pkt_exp.hex()


class TestForward:
    def test_ipv4_ttl_decrement(self):
        """Forward IPv4: rewrite MACs, decrement TTL, update IP checksum."""
        new_dst = mac('de:ad:be:ef:00:01')
        new_src = mac('de:ad:be:ef:00:02')

        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip

        ip_fwd = make_ipv4('10.0.0.1', '10.0.0.2', 63, 1, ICMP_REQ)
        pkt_exp = make_eth(new_dst, new_src, 0x0800) + ip_fwd

        assert run_engine(pkt_in.hex(),
                          'forward de:ad:be:ef:00:01 de:ad:be:ef:00:02') == pkt_exp.hex()

    def test_ipv6_hop_decrement(self):
        """Forward IPv6: rewrite MACs and decrement hop limit."""
        new_dst = mac('de:ad:be:ef:00:01')
        new_src = mac('de:ad:be:ef:00:02')

        icmpv6 = make_icmpv6_echo(128, 0x5678, 1, ICMPV6_DATA,
                                  IPV6_SRC, IPV6_DST)
        ip6 = make_ipv6(IPV6_SRC, IPV6_DST, 64, 58, len(icmpv6))
        pkt_in = make_eth(DST, SRC, 0x86DD) + ip6 + icmpv6

        ip6_fwd = make_ipv6(IPV6_SRC, IPV6_DST, 63, 58, len(icmpv6))
        pkt_exp = make_eth(new_dst, new_src, 0x86DD) + ip6_fwd + icmpv6

        assert run_engine(pkt_in.hex(),
                          'forward de:ad:be:ef:00:01 de:ad:be:ef:00:02') == pkt_exp.hex()

    def test_ipv4_ttl_expire(self):
        """Forward with TTL=1 should drop the packet."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 1, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(),
                          'forward de:ad:be:ef:00:01 de:ad:be:ef:00:02') == ''

    def test_ipv6_hop_expire(self):
        """Forward with hop_limit=1 should drop the packet."""
        icmpv6 = make_icmpv6_echo(128, 0x5678, 1, ICMPV6_DATA,
                                  IPV6_SRC, IPV6_DST)
        ip6 = make_ipv6(IPV6_SRC, IPV6_DST, 1, 58, len(icmpv6))
        pkt_in = make_eth(DST, SRC, 0x86DD) + ip6 + icmpv6
        assert run_engine(pkt_in.hex(),
                          'forward de:ad:be:ef:00:01 de:ad:be:ef:00:02') == ''


class TestFilter:
    def test_drop_icmp(self):
        """Filter icmp should drop an ICMP packet."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'filter icmp') == ''

    def test_pass_wrong_proto(self):
        """Filter udp should pass an ICMP packet through unchanged."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'filter udp') == pkt_in.hex()

    def test_drop_udp(self):
        """Filter udp should drop a UDP packet."""
        udp = make_udp(12345, 80, b'\xaa' * 10)
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 17, udp)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'filter udp') == ''

    def test_vlan_tagged_filter(self):
        """Filter should work through VLAN tags."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x8100) + make_vlan(42, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'filter icmp') == ''


# ================================================================
# Tests — tag operation (DNA)
# ================================================================

class TestTag:
    def test_basic_ipv4(self):
        """Tag an IPv4 ICMP packet with key=42."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip

        digest = compute_tag_digest(pkt_in)
        trailer = make_tag_trailer(42, 0x0800, digest)
        pkt_exp = pkt_in + trailer

        assert run_engine(pkt_in.hex(), 'tag 42') == pkt_exp.hex()

    def test_ipv6(self):
        """Tag an IPv6 ICMPv6 packet with key=256."""
        icmpv6 = make_icmpv6_echo(128, 0x5678, 1, ICMPV6_DATA,
                                  IPV6_SRC, IPV6_DST)
        ip6 = make_ipv6(IPV6_SRC, IPV6_DST, 64, 58, len(icmpv6))
        pkt_in = make_eth(DST, SRC, 0x86DD) + ip6 + icmpv6

        digest = compute_tag_digest(pkt_in)
        trailer = make_tag_trailer(256, 0x86DD, digest)
        pkt_exp = pkt_in + trailer

        assert run_engine(pkt_in.hex(), 'tag 256') == pkt_exp.hex()

    def test_vlan_tagged(self):
        """Tag a VLAN-tagged packet — L3 EtherType should be IPv4, not VLAN."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x8100) + make_vlan(42, 0x0800) + ip

        digest = compute_tag_digest(pkt_in)
        # L3 proto must be 0x0800 (IPv4), not 0x8100 (VLAN)
        trailer = make_tag_trailer(7, 0x0800, digest)
        pkt_exp = pkt_in + trailer

        assert run_engine(pkt_in.hex(), 'tag 7') == pkt_exp.hex()

    def test_udp_packet(self):
        """Tag a UDP packet with key=1000 — different L4 than ICMP."""
        udp = make_udp(5353, 5353, b'\xde\xad\xbe\xef' * 4)
        ip = make_ipv4('192.168.1.1', '224.0.0.251', 255, 17, udp)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip

        digest = compute_tag_digest(pkt_in)
        trailer = make_tag_trailer(1000, 0x0800, digest)
        pkt_exp = pkt_in + trailer

        assert run_engine(pkt_in.hex(), 'tag 1000') == pkt_exp.hex()


# ================================================================
# Tests — untag operation (DNA)
# ================================================================

class TestUntag:
    def test_roundtrip(self):
        """Tag then untag should produce the original packet."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'tag 42', 'untag') == pkt_in.hex()

    def test_no_trailer_drops(self):
        """Untag on a packet without a valid trailer should drop."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'untag') == ''

    def test_bad_digest_drops(self):
        """Untag should drop if the digest doesn't match."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        bad_trailer = struct.pack('!IHHI', TAG_MAGIC, 42, 0x0800, 0xDEADBEEF)
        bad_pkt = pkt_in + bad_trailer
        assert run_engine(bad_pkt.hex(), 'untag') == ''

    def test_roundtrip_ipv6(self):
        """Tag then untag an IPv6 packet."""
        icmpv6 = make_icmpv6_echo(128, 0x5678, 1, ICMPV6_DATA,
                                  IPV6_SRC, IPV6_DST)
        ip6 = make_ipv6(IPV6_SRC, IPV6_DST, 64, 58, len(icmpv6))
        pkt_in = make_eth(DST, SRC, 0x86DD) + ip6 + icmpv6
        assert run_engine(pkt_in.hex(), 'tag 100', 'untag') == pkt_in.hex()


# ================================================================
# Tests — standard pipelines
# ================================================================

class TestPipeline:
    def test_pop_reply_push(self):
        """Pipeline: vlan-pop -> echo-reply -> vlan-push 100."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x8100) + make_vlan(42, 0x0800) + ip

        ip_reply = make_ipv4('10.0.0.2', '10.0.0.1', 64, 1, ICMP_REPLY)
        pkt_exp = (make_eth(SRC, DST, 0x8100) +
                   make_vlan(100, 0x0800) + ip_reply)

        assert run_engine(pkt_in.hex(),
                          'vlan-pop', 'echo-reply', 'vlan-push 100') == pkt_exp.hex()

    def test_forward_then_filter_pass(self):
        """Pipeline: forward + filter udp on an ICMP packet — should pass."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip

        ip_fwd = make_ipv4('10.0.0.1', '10.0.0.2', 63, 1, ICMP_REQ)
        new_dst = mac('de:ad:be:ef:00:01')
        new_src = mac('de:ad:be:ef:00:02')
        pkt_exp = make_eth(new_dst, new_src, 0x0800) + ip_fwd

        assert run_engine(pkt_in.hex(),
                          'forward de:ad:be:ef:00:01 de:ad:be:ef:00:02',
                          'filter udp') == pkt_exp.hex()

    def test_double_vlan_pop(self):
        """Pipeline: two vlan-pops to strip Q-in-Q down to untagged."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = (make_eth(DST, SRC, 0x88A8) +
                  make_vlan(100, 0x8100) +
                  make_vlan(200, 0x0800) + ip)
        pkt_exp = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(), 'vlan-pop', 'vlan-pop') == pkt_exp.hex()


# ================================================================
# Tests — tag pipelines (DNA: combines standard + custom ops)
# ================================================================

class TestTagPipeline:
    def test_forward_then_tag(self):
        """Forward then tag: digest is computed on the forwarded packet."""
        new_dst = mac('de:ad:be:ef:00:01')
        new_src = mac('de:ad:be:ef:00:02')

        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip

        ip_fwd = make_ipv4('10.0.0.1', '10.0.0.2', 63, 1, ICMP_REQ)
        forwarded = make_eth(new_dst, new_src, 0x0800) + ip_fwd

        digest = compute_tag_digest(forwarded)
        trailer = make_tag_trailer(7, 0x0800, digest)
        pkt_exp = forwarded + trailer

        assert run_engine(pkt_in.hex(),
                          'forward de:ad:be:ef:00:01 de:ad:be:ef:00:02',
                          'tag 7') == pkt_exp.hex()

    def test_echo_reply_then_tag(self):
        """Echo-reply then tag: digest computed on the reply packet."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip

        ip_reply = make_ipv4('10.0.0.2', '10.0.0.1', 64, 1, ICMP_REPLY)
        reply_pkt = make_eth(SRC, DST, 0x0800) + ip_reply

        digest = compute_tag_digest(reply_pkt)
        trailer = make_tag_trailer(55, 0x0800, digest)
        pkt_exp = reply_pkt + trailer

        assert run_engine(pkt_in.hex(), 'echo-reply', 'tag 55') == pkt_exp.hex()

    def test_push_tag_untag_pop_roundtrip(self):
        """Complex pipeline: vlan-push -> tag -> untag -> vlan-pop = identity."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(),
                          'vlan-push 42', 'tag 99', 'untag', 'vlan-pop') == pkt_in.hex()

    def test_tag_forward_untag_drops(self):
        """Tag then forward then untag: forward changes the packet so digest
        no longer matches the original — untag must drop."""
        ip = make_ipv4('10.0.0.1', '10.0.0.2', 64, 1, ICMP_REQ)
        pkt_in = make_eth(DST, SRC, 0x0800) + ip
        assert run_engine(pkt_in.hex(),
                          'tag 10',
                          'forward de:ad:be:ef:00:01 de:ad:be:ef:00:02',
                          'untag') == ''

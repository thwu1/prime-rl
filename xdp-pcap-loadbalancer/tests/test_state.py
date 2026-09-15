"""Tests for XDP-style load balancer pcap processor.

Verifies output.pcap correctness (checksums, flow affinity, special packets)
and stats.json consistency.
"""


import struct
import json
import os
import pytest

OUTPUT_PCAP = "/app/output.pcap"
STATS_FILE  = "/app/stats.json"
INPUT_PCAP  = "/app/input.pcap"
CONFIG_FILE = "/app/config.json"


# ── helpers ──────────────────────────────────────────────────────────

def compute_checksum(data: bytes) -> int:
    """RFC 1071 one's complement checksum."""
    if len(data) % 2:
        data = data + b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


def read_pcap_packets(path):
    """Return list of raw packet byte strings from a pcap file."""
    with open(path, 'rb') as f:
        hdr = f.read(24)
        magic = struct.unpack('<I', hdr[:4])[0]
        assert magic == 0xa1b2c3d4, f"Bad pcap magic: {magic:#x}"
        packets = []
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', rec)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            packets.append(data)
    return packets


def parse_eth(pkt):
    """Return (dst, src, ethertype, header_len, vlan_id|None) or None."""
    if len(pkt) < 14:
        return None
    dst = pkt[0:6]
    src = pkt[6:12]
    etype = struct.unpack('!H', pkt[12:14])[0]
    hlen = 14
    vid = None
    if etype == 0x8100:
        if len(pkt) < 18:
            return None
        tci = struct.unpack('!H', pkt[14:16])[0]
        vid = tci & 0x0FFF
        etype = struct.unpack('!H', pkt[16:18])[0]
        hlen = 18
    return dst, src, etype, hlen, vid


# ── tests ────────────────────────────────────────────────────────────

class TestOutputExists:
    def test_output_pcap_exists(self):
        assert os.path.exists(OUTPUT_PCAP), "output.pcap not found"

    def test_stats_exists(self):
        assert os.path.exists(STATS_FILE), "stats.json not found"


class TestPcapFormat:
    def test_valid_pcap(self):
        pkts = read_pcap_packets(OUTPUT_PCAP)
        assert len(pkts) > 0

    def test_correct_packet_count(self):
        """11 input packets -> 10 output (1 truncated dropped)."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        assert len(pkts) == 10, f"Expected 10, got {len(pkts)}"


class TestChecksums:
    """Every IPv4 packet in the output must have correct checksums."""

    def _output_packets(self):
        return read_pcap_packets(OUTPUT_PCAP)

    def test_ip_checksums(self):
        for i, pkt in enumerate(self._output_packets()):
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            ip_hdr = bytearray(pkt[hlen:hlen + 20])
            stored = struct.unpack('!H', ip_hdr[10:12])[0]
            ip_hdr[10:12] = b'\x00\x00'
            computed = compute_checksum(bytes(ip_hdr))
            assert stored == computed, (
                f"Pkt {i}: IP csum mismatch stored={stored:#06x} "
                f"computed={computed:#06x}"
            )

    def test_tcp_checksums(self):
        for i, pkt in enumerate(self._output_packets()):
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            if pkt[hlen + 9] != 6:
                continue
            ihl = (pkt[hlen] & 0x0F) * 4
            tcp_off = hlen + ihl
            if len(pkt) < tcp_off + 20:
                continue
            src_ip = pkt[hlen + 12:hlen + 16]
            dst_ip = pkt[hlen + 16:hlen + 20]
            tcp = bytearray(pkt[tcp_off:])
            stored = struct.unpack('!H', tcp[16:18])[0]
            tcp[16:18] = b'\x00\x00'
            pseudo = src_ip + dst_ip + struct.pack('!BBH', 0, 6, len(tcp))
            computed = compute_checksum(pseudo + bytes(tcp))
            assert stored == computed, (
                f"Pkt {i}: TCP csum mismatch stored={stored:#06x} "
                f"computed={computed:#06x}"
            )

    def test_udp_checksums(self):
        for i, pkt in enumerate(self._output_packets()):
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            if pkt[hlen + 9] != 17:
                continue
            ihl = (pkt[hlen] & 0x0F) * 4
            udp_off = hlen + ihl
            if len(pkt) < udp_off + 8:
                continue
            stored = struct.unpack('!H', pkt[udp_off + 6:udp_off + 8])[0]
            if stored == 0:
                continue  # checksum disabled
            src_ip = pkt[hlen + 12:hlen + 16]
            dst_ip = pkt[hlen + 16:hlen + 20]
            udp = bytearray(pkt[udp_off:])
            udp[6:8] = b'\x00\x00'
            pseudo = src_ip + dst_ip + struct.pack('!BBH', 0, 17, len(udp))
            computed = compute_checksum(pseudo + bytes(udp))
            assert stored == computed, (
                f"Pkt {i}: UDP csum mismatch stored={stored:#06x} "
                f"computed={computed:#06x}"
            )


class TestUDPChecksumZero:
    def test_udp_checksum_zero_preserved(self):
        """UDP packet with checksum=0 in input must keep checksum=0 in output."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        found = False
        for pkt in pkts:
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            if pkt[hlen + 9] != 17:
                continue
            ihl = (pkt[hlen] & 0x0F) * 4
            udp_off = hlen + ihl
            if len(pkt) < udp_off + 8:
                continue
            sport = struct.unpack('!H', pkt[udp_off:udp_off + 2])[0]
            if sport == 7777:
                csum = struct.unpack('!H', pkt[udp_off + 6:udp_off + 8])[0]
                assert csum == 0, (
                    f"UDP checksum for sport=7777 should be 0 (disabled), "
                    f"got {csum:#06x}"
                )
                found = True
                break
        assert found, "UDP flow with sport=7777 not found in output"


class TestICMP:
    def test_icmp_echo_reply(self):
        """Must contain one ICMP echo reply from VIP to 192.168.1.40."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        found = False
        for pkt in pkts:
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            if pkt[hlen + 9] != 1:
                continue
            ihl = (pkt[hlen] & 0x0F) * 4
            icmp_off = hlen + ihl
            if len(pkt) < icmp_off + 8:
                continue
            if pkt[icmp_off] != 0:  # type 0 = echo reply
                continue
            found = True
            src = struct.unpack('!I', pkt[hlen + 12:hlen + 16])[0]
            assert src == 0x0A000001, f"ICMP reply src != VIP: {src:#010x}"
            dst = struct.unpack('!I', pkt[hlen + 16:hlen + 20])[0]
            assert dst == 0xC0A80128, f"ICMP reply dst wrong: {dst:#010x}"
            icmp_id = struct.unpack('!H', pkt[icmp_off + 4:icmp_off + 6])[0]
            assert icmp_id == 0x1234, f"ICMP ID mismatch: {icmp_id:#06x}"
            icmp_data = bytearray(pkt[icmp_off:])
            icmp_data[2:4] = b'\x00\x00'
            csum = compute_checksum(bytes(icmp_data))
            stored = struct.unpack('!H', pkt[icmp_off + 2:icmp_off + 4])[0]
            assert stored == csum, "ICMP reply checksum invalid"
            break
        assert found, "No ICMP echo reply in output"


class TestARP:
    def test_arp_reply(self):
        """Must contain an ARP reply for VIP with LB MAC."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        lb_mac = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0xfe])
        found = False
        for pkt in pkts:
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0806:
                continue
            if len(pkt) < hlen + 28:
                continue
            oper = struct.unpack('!H', pkt[hlen + 6:hlen + 8])[0]
            if oper != 2:
                continue
            found = True
            sha = pkt[hlen + 8:hlen + 14]
            assert sha == lb_mac, f"ARP SHA != LB MAC: {sha.hex()}"
            spa = struct.unpack('!I', pkt[hlen + 14:hlen + 18])[0]
            assert spa == 0x0A000001, f"ARP SPA != VIP: {spa:#010x}"
            tha = pkt[hlen + 18:hlen + 24]
            assert tha == bytes([0x02, 0x00, 0x00, 0xaa, 0x00, 0x05])
            tpa = struct.unpack('!I', pkt[hlen + 24:hlen + 28])[0]
            assert tpa == 0xC0A80132, f"ARP TPA wrong: {tpa:#010x}"
            break
        assert found, "No ARP reply in output"


class TestFlowAffinity:
    def test_same_flow_same_backend(self):
        """Packets with same 5-tuple must go to the same backend IP."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        backend_ips = {struct.unpack('!I', bytes(int(x) for x in b['ip'].split('.')))[0]
                       for b in cfg['backends']}

        flow_dsts = {}
        for pkt in pkts:
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            proto = pkt[hlen + 9]
            if proto not in (6, 17):
                continue
            ihl = (pkt[hlen] & 0x0F) * 4
            t_off = hlen + ihl
            if len(pkt) < t_off + 4:
                continue
            sport = struct.unpack('!H', pkt[t_off:t_off + 2])[0]
            dst_ip = struct.unpack('!I', pkt[hlen + 16:hlen + 20])[0]
            if dst_ip not in backend_ips:
                continue
            flow_dsts.setdefault(sport, set()).add(dst_ip)

        for sport, dsts in flow_dsts.items():
            assert len(dsts) == 1, (
                f"Flow src_port={sport} routed to multiple backends: "
                f"{[hex(d) for d in dsts]}"
            )


class TestVLAN:
    def test_vlan_tag_preserved(self):
        """VLAN-tagged input packet should have its tag in the output."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        found = False
        for pkt in pkts:
            if len(pkt) < 18:
                continue
            etype = struct.unpack('!H', pkt[12:14])[0]
            if etype != 0x8100:
                continue
            found = True
            tci = struct.unpack('!H', pkt[14:16])[0]
            vid = tci & 0x0FFF
            assert vid == 100, f"VLAN ID should be 100, got {vid}"
            inner = struct.unpack('!H', pkt[16:18])[0]
            assert inner == 0x0800, f"Inner ethertype should be 0x0800, got {inner:#06x}"
            break
        assert found, "No VLAN-tagged packet in output"


class TestPassthrough:
    def test_ipv6_unchanged(self):
        """IPv6 packet must pass through byte-for-byte identical."""
        inp = read_pcap_packets(INPUT_PCAP)
        out = read_pcap_packets(OUTPUT_PCAP)

        ipv6_in = None
        for pkt in inp:
            if len(pkt) >= 14:
                et = struct.unpack('!H', pkt[12:14])[0]
                if et == 0x86DD:
                    ipv6_in = pkt
                    break
        assert ipv6_in is not None

        ipv6_out = None
        for pkt in out:
            if len(pkt) >= 14:
                et = struct.unpack('!H', pkt[12:14])[0]
                if et == 0x86DD:
                    ipv6_out = pkt
                    break
        assert ipv6_out is not None, "IPv6 not passed through"
        assert ipv6_in == ipv6_out, "IPv6 packet was modified"


class TestLBAddresses:
    def test_lb_packets_have_correct_macs(self):
        """LB'd packets: src_mac = LB MAC, dst_mac = backend MAC."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        lb_mac = bytes(int(x, 16) for x in cfg['lb_mac'].split(':'))
        bmacs = {bytes(int(x, 16) for x in b['mac'].split(':'))
                 for b in cfg['backends']}
        bips = {struct.unpack('!I', bytes(int(x) for x in b['ip'].split('.')))[0]
                for b in cfg['backends']}

        checked = 0
        for pkt in pkts:
            eth = parse_eth(pkt)
            if eth is None:
                continue
            dmac, smac, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            proto = pkt[hlen + 9]
            dst_ip = struct.unpack('!I', pkt[hlen + 16:hlen + 20])[0]
            if proto in (6, 17) and dst_ip in bips:
                assert smac == lb_mac, f"LB pkt src_mac != LB MAC"
                assert dmac in bmacs, f"LB pkt dst_mac not a backend MAC"
                checked += 1
        assert checked >= 7, f"Expected >=7 LB'd packets, found {checked}"

    def test_lb_packets_src_ip(self):
        """LB'd packets must have LB IP as source."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        lb_ip = struct.unpack('!I', bytes(int(x) for x in cfg['lb_ip'].split('.')))[0]
        bips = {struct.unpack('!I', bytes(int(x) for x in b['ip'].split('.')))[0]
                for b in cfg['backends']}

        for pkt in pkts:
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            proto = pkt[hlen + 9]
            dst_ip = struct.unpack('!I', pkt[hlen + 16:hlen + 20])[0]
            if proto in (6, 17) and dst_ip in bips:
                src_ip = struct.unpack('!I', pkt[hlen + 12:hlen + 16])[0]
                assert src_ip == lb_ip, (
                    f"LB pkt src_ip should be LB IP {lb_ip:#010x}, "
                    f"got {src_ip:#010x}"
                )

    def test_no_vip_as_tcp_udp_destination(self):
        """No TCP/UDP packet in output should still target the VIP."""
        pkts = read_pcap_packets(OUTPUT_PCAP)
        vip = 0x0A000001
        for pkt in pkts:
            eth = parse_eth(pkt)
            if eth is None:
                continue
            _, _, etype, hlen, _ = eth
            if etype != 0x0800 or len(pkt) < hlen + 20:
                continue
            proto = pkt[hlen + 9]
            if proto in (6, 17):
                dst = struct.unpack('!I', pkt[hlen + 16:hlen + 20])[0]
                assert dst != vip, "TCP/UDP packet still has VIP as dst"


class TestStats:
    def _stats(self):
        with open(STATS_FILE) as f:
            return json.load(f)

    def test_summary_counts(self):
        s = self._stats()['summary']
        assert s['total_input'] == 11
        assert s['total_output'] == 10
        assert s['dropped'] == 1
        assert s['load_balanced'] == 7
        assert s['icmp_replies'] == 1
        assert s['arp_replies'] == 1
        assert s['passthrough'] == 1

    def test_flows(self):
        stats = self._stats()
        flows = stats['flows']
        assert len(flows) == 6, f"Expected 6 flows, got {len(flows)}"
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        valid_backends = {b['ip'] for b in cfg['backends']}
        total_flow_pkts = 0
        for fl in flows:
            for key in ('src_ip', 'dst_ip', 'src_port', 'dst_port',
                        'protocol', 'packet_count', 'backend_ip'):
                assert key in fl, f"Flow missing key '{key}'"
            assert fl['packet_count'] > 0
            assert fl['backend_ip'] in valid_backends
            total_flow_pkts += fl['packet_count']
        assert total_flow_pkts == 7

    def test_backend_consistency(self):
        stats = self._stats()
        backends = stats['backends']
        total = sum(b['packet_count'] for b in backends)
        assert total == stats['summary']['load_balanced'], (
            f"Backend pkt sum {total} != load_balanced "
            f"{stats['summary']['load_balanced']}"
        )
        for b in backends:
            assert 'ip' in b
            assert 'byte_count' in b

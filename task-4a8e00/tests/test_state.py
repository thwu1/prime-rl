
import json
import os
import pytest

OUTPUT_FILE = "/app/output/results.json"


def load_results():
    with open(OUTPUT_FILE) as f:
        return json.load(f)


def find_entry(data, src_ip, dst_ip=None):
    """Find entry by source IP and optionally destination IP."""
    results = [e for e in data if e.get("src_ip") == src_ip]
    if dst_ip is not None:
        results = [e for e in results if e.get("dst_ip") == dst_ip]
    assert len(results) == 1, (
        f"Expected 1 entry for src_ip={src_ip} dst_ip={dst_ip}, got {len(results)}")
    return results[0]


# ====== Output Structure ======

class TestOutputStructure:
    def test_output_file_exists(self):
        assert os.path.isfile(OUTPUT_FILE), "results.json not found"

    def test_valid_json_array(self):
        data = load_results()
        assert isinstance(data, list), "results.json must be a JSON array"

    def test_total_packet_count(self):
        """12 classified packets: 8 SYN + 4 SYN+ACK."""
        data = load_results()
        assert len(data) == 12, f"Expected 12 entries, got {len(data)}"

    def test_required_fields(self):
        data = load_results()
        required = {"src_ip", "src_port", "dst_ip", "dst_port",
                     "signature", "match", "packet_type", "timestamp"}
        for entry in data:
            missing = required - set(entry.keys())
            assert not missing, (
                f"Missing fields {missing} in entry for {entry.get('src_ip', '?')}")

    def test_signature_format(self):
        """All signatures must have exactly 8 colon-separated fields."""
        data = load_results()
        for entry in data:
            parts = entry["signature"].split(":")
            assert len(parts) == 8, (
                f"Signature has {len(parts)} fields, expected 8: {entry['signature']}")


# ====== Packet Type Classification ======

class TestPacketTypes:
    def test_syn_count(self):
        data = load_results()
        syn = [e for e in data if e.get("packet_type") == "syn"]
        assert len(syn) == 8, f"Expected 8 SYN entries, got {len(syn)}"

    def test_synack_count(self):
        data = load_results()
        sa = [e for e in data if e.get("packet_type") == "syn+ack"]
        assert len(sa) == 4, f"Expected 4 SYN+ACK entries, got {len(sa)}"

    def test_valid_packet_types(self):
        data = load_results()
        for entry in data:
            assert entry["packet_type"] in ("syn", "syn+ack"), (
                f"Invalid packet_type: {entry['packet_type']}")


# ====== SYN OS Matching (tcp:request section) ======

class TestSynMatching:
    def test_linux6_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        assert entry["match"] == "Linux:6.x"
        assert entry["packet_type"] == "syn"

    def test_windows11_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.2.20")
        assert entry["match"] == "Windows:11"
        assert entry["packet_type"] == "syn"

    def test_macos14_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.3.30")
        assert entry["match"] == "macOS:14.x"
        assert entry["packet_type"] == "syn"

    def test_freebsd14_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.4.40")
        assert entry["match"] == "FreeBSD:14.x"
        assert entry["packet_type"] == "syn"

    def test_linux_ecn_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.5.50")
        assert entry["match"] == "Linux:6.x-ecn"
        assert entry["packet_type"] == "syn"

    def test_openbsd7_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.6.60")
        assert entry["match"] == "OpenBSD:7.x"
        assert entry["packet_type"] == "syn"

    def test_unknown_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.7.70")
        assert entry["match"] == "unknown"
        assert entry["packet_type"] == "syn"

    def test_linux_ipopt_match(self):
        data = load_results()
        entry = find_entry(data, "10.0.8.80")
        assert entry["match"] == "Linux:6.x-ipopt"
        assert entry["packet_type"] == "syn"


# ====== SYN+ACK OS Matching (tcp:response section) ======

class TestSynAckMatching:
    def test_linux6_synack(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.1.10")
        assert entry["match"] == "Linux:6.x"
        assert entry["packet_type"] == "syn+ack"

    def test_windows_server_synack(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.2.20")
        assert entry["match"] == "Windows:Server"
        assert entry["packet_type"] == "syn+ack"

    def test_linux_ecn_synack(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.3.30")
        assert entry["match"] == "Linux:6.x-ecn"
        assert entry["packet_type"] == "syn+ack"

    def test_freebsd_synack(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.4.40")
        assert entry["match"] == "FreeBSD:14.x"
        assert entry["packet_type"] == "syn+ack"


# ====== Signature Field Accuracy ======

class TestSignatureDetails:
    def test_ip_options_olen(self):
        """Packet with IP options must show olen=4."""
        data = load_results()
        entry = find_entry(data, "10.0.8.80")
        olen = entry["signature"].split(":")[2]
        assert olen == "4", f"Expected olen=4, got {olen}"

    def test_normal_olen_zero(self):
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        olen = entry["signature"].split(":")[2]
        assert olen == "0", f"Expected olen=0, got {olen}"

    def test_macos_eol_padding(self):
        data = load_results()
        entry = find_entry(data, "10.0.3.30")
        olayout = entry["signature"].split(":")[5]
        assert "eol+1" in olayout, f"Expected eol+1 in olayout: {olayout}"

    def test_unknown_eol_padding(self):
        data = load_results()
        entry = find_entry(data, "10.0.7.70")
        olayout = entry["signature"].split(":")[5]
        assert "eol+0" in olayout, f"Expected eol+0 in olayout: {olayout}"

    def test_windows_olayout(self):
        data = load_results()
        entry = find_entry(data, "10.0.2.20")
        olayout = entry["signature"].split(":")[5]
        assert olayout == "mss,nop,ws,nop,nop,sok", f"Wrong olayout: {olayout}"

    def test_openbsd_olayout(self):
        data = load_results()
        entry = find_entry(data, "10.0.6.60")
        olayout = entry["signature"].split(":")[5]
        assert olayout == "mss,nop,nop,sok,nop,ws,nop,nop,ts", (
            f"Wrong olayout: {olayout}")

    def test_linux_olayout(self):
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        olayout = entry["signature"].split(":")[5]
        assert olayout == "mss,sok,ts,nop,ws", f"Wrong olayout: {olayout}"

    def test_unknown_mss_value(self):
        data = load_results()
        entry = find_entry(data, "10.0.7.70")
        mss = entry["signature"].split(":")[3]
        assert mss == "536", f"Expected MSS=536, got {mss}"

    def test_window_field(self):
        """Verify raw window value in signature."""
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        ww = entry["signature"].split(":")[4]
        assert ww == "29200,7", f"Wrong window field: {ww}"

    def test_synack_window_field(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.1.10")
        ww = entry["signature"].split(":")[4]
        assert ww == "28960,7", f"Wrong SYN+ACK window field: {ww}"


# ====== TTL Normalization ======

class TestTTLNormalization:
    def test_ttl_64_stays_64(self):
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        ittl = entry["signature"].split(":")[1]
        assert ittl == "64", f"TTL=64 should stay 64, got {ittl}"

    def test_ttl_128_stays_128(self):
        data = load_results()
        entry = find_entry(data, "10.0.2.20")
        ittl = entry["signature"].split(":")[1]
        assert ittl == "128", f"TTL=128 should stay 128, got {ittl}"

    def test_ttl_63_normalizes_to_64(self):
        data = load_results()
        entry = find_entry(data, "10.0.5.50")
        ittl = entry["signature"].split(":")[1]
        assert ittl == "64", f"TTL=63 should normalize to 64, got {ittl}"

    def test_ttl_255_stays_255(self):
        data = load_results()
        entry = find_entry(data, "10.0.7.70")
        ittl = entry["signature"].split(":")[1]
        assert ittl == "255", f"TTL=255 should stay 255, got {ittl}"

    def test_synack_ttl_63_normalizes(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.3.30")
        ittl = entry["signature"].split(":")[1]
        assert ittl == "64", f"SYN+ACK TTL=63 should normalize to 64, got {ittl}"


# ====== Quirk Detection ======

class TestQuirkDetection:
    def test_df_and_id_plus(self):
        """DF set + non-zero IP ID -> df, id+."""
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "df" in qset, f"Missing df: {quirks}"
        assert "id+" in qset, f"Missing id+: {quirks}"

    def test_df_without_id_plus(self):
        """DF set + zero IP ID -> df only, no id+."""
        data = load_results()
        entry = find_entry(data, "10.0.3.30")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "df" in qset, f"Missing df: {quirks}"
        assert "id+" not in qset, f"Spurious id+: {quirks}"

    def test_id_minus(self):
        """No DF + zero IP ID -> id- quirk."""
        data = load_results()
        entry = find_entry(data, "10.0.7.70")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "id-" in qset, f"Missing id-: {quirks}"
        assert "df" not in qset, f"Spurious df: {quirks}"

    def test_ecn_quirk(self):
        data = load_results()
        entry = find_entry(data, "10.0.5.50")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "ecn" in qset, f"Missing ecn: {quirks}"

    def test_ack_plus_quirk(self):
        """Non-zero ACK number without ACK flag -> ack+."""
        data = load_results()
        entry = find_entry(data, "10.0.5.50")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "ack+" in qset, f"Missing ack+: {quirks}"

    def test_ts1_minus(self):
        """Zero TSval -> ts1-."""
        data = load_results()
        entry = find_entry(data, "10.0.7.70")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "ts1-" in qset, f"Missing ts1-: {quirks}"

    def test_ts2_plus_in_syn(self):
        """Non-zero TSecr in SYN -> ts2+ (anomalous for initial SYN)."""
        data = load_results()
        entry = find_entry(data, "10.0.7.70")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "ts2+" in qset, f"Missing ts2+: {quirks}"

    def test_ts2_plus_in_synack(self):
        """Non-zero TSecr in SYN+ACK -> ts2+ (normal echo behavior)."""
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.1.10")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "ts2+" in qset, f"Missing ts2+ in SYN+ACK: {quirks}"

    def test_ecn_in_synack(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.3.30")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "ecn" in qset, f"Missing ecn in SYN+ACK: {quirks}"
        assert "df" in qset, f"Missing df in SYN+ACK: {quirks}"

    def test_synack_id_plus(self):
        """Windows SYN+ACK: DF + non-zero ID -> id+."""
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.2.20")
        quirks = entry["signature"].split(":")[6]
        qset = set(quirks.split(","))
        assert "id+" in qset, f"Missing id+ in Windows SYN+ACK: {quirks}"

    def test_freebsd_synack_no_ts2_plus(self):
        """FreeBSD SYN+ACK without timestamps: no ts2+ quirk."""
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.4.40")
        quirks = entry["signature"].split(":")[6]
        qset = set(q for q in quirks.split(",") if q)
        assert "ts2+" not in qset, f"Spurious ts2+ in FreeBSD SYN+ACK: {quirks}"


# ====== Packet Filtering ======

class TestFiltering:
    def test_ack_only_excluded(self):
        data = load_results()
        results = [e for e in data if e.get("src_ip") == "10.0.9.90"]
        assert len(results) == 0, "ACK-only packet should be excluded"

    def test_rst_excluded(self):
        data = load_results()
        results = [e for e in data if e.get("src_ip") == "10.0.10.100"]
        assert len(results) == 0, "RST packet should be excluded"

    def test_data_packet_excluded(self):
        """Non-SYN data packet from server.pcapng must not appear."""
        data = load_results()
        results = [e for e in data
                   if e.get("src_ip") == "192.168.1.1"
                   and e.get("dst_ip") == "10.0.1.10"]
        assert len(results) == 1, (
            f"Expected 1 entry for 192.168.1.1->10.0.1.10 (SYN+ACK only), got {len(results)}")

    def test_no_duplicate_entries(self):
        data = load_results()
        tuples = [(e["src_ip"], e["src_port"], e["dst_ip"], e["dst_port"])
                  for e in data]
        assert len(tuples) == len(set(tuples)), "Duplicate entries found"


# ====== Network Field Accuracy ======

class TestNetworkFields:
    def test_syn_ports(self):
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        assert entry["src_port"] == 45678
        assert entry["dst_port"] == 443

    def test_synack_ports(self):
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.2.20")
        assert entry["src_port"] == 80
        assert entry["dst_port"] == 52000

    def test_freebsd_syn_ports(self):
        data = load_results()
        entry = find_entry(data, "10.0.4.40")
        assert entry["src_port"] == 39876
        assert entry["dst_port"] == 22

    def test_timestamp_accuracy(self):
        """Timestamp must match PCAP value (verifies binary parsing)."""
        data = load_results()
        entry = find_entry(data, "10.0.1.10")
        assert abs(entry["timestamp"] - 1700000001.123456) < 0.001, (
            f"Timestamp mismatch: {entry['timestamp']}")

    def test_synack_timestamp(self):
        """Timestamp from pcapng must be correctly extracted."""
        data = load_results()
        entry = find_entry(data, "192.168.1.1", "10.0.1.10")
        assert abs(entry["timestamp"] - 1700000021.111111) < 0.001, (
            f"SYN+ACK timestamp mismatch: {entry['timestamp']}")

    def test_all_syn_dst_ips(self):
        """All SYN packets target 192.168.1.1."""
        data = load_results()
        for e in data:
            if e.get("packet_type") == "syn":
                assert e["dst_ip"] == "192.168.1.1", (
                    f"Wrong dst_ip {e['dst_ip']} for SYN from {e['src_ip']}")

    def test_all_synack_src_ips(self):
        """All SYN+ACK packets originate from 192.168.1.1."""
        data = load_results()
        for e in data:
            if e.get("packet_type") == "syn+ack":
                assert e["src_ip"] == "192.168.1.1", (
                    f"Wrong src_ip {e['src_ip']} for SYN+ACK to {e['dst_ip']}")


# ====== Multi-format Capture Handling ======

class TestCaptureFormats:
    def test_pcap_packets_parsed(self):
        """Client SYN packets from standard pcap must be present."""
        data = load_results()
        syn_ips = {e["src_ip"] for e in data if e["packet_type"] == "syn"}
        expected = {"10.0.1.10", "10.0.2.20", "10.0.3.30", "10.0.4.40",
                    "10.0.5.50", "10.0.6.60", "10.0.7.70", "10.0.8.80"}
        assert syn_ips == expected, f"Missing SYN sources: {expected - syn_ips}"

    def test_pcapng_packets_parsed(self):
        """Server SYN+ACK packets from pcapng must be present."""
        data = load_results()
        sa_dsts = {e["dst_ip"] for e in data if e["packet_type"] == "syn+ack"}
        expected = {"10.0.1.10", "10.0.2.20", "10.0.3.30", "10.0.4.40"}
        assert sa_dsts == expected, f"Missing SYN+ACK destinations: {expected - sa_dsts}"

    def test_pcapng_noise_filtered(self):
        """ACK-only data packet in server.pcapng must be excluded."""
        data = load_results()
        sa_from_server = [e for e in data
                          if e["src_ip"] == "192.168.1.1"
                          and e["packet_type"] == "syn+ack"]
        assert len(sa_from_server) == 4, (
            f"Expected exactly 4 SYN+ACK from server, got {len(sa_from_server)}")


# ====== Database Schema Handling ======

class TestDatabaseAccess:
    def test_request_section_labels_correct(self):
        """Verify all tcp:request matches come from correct OS labels."""
        data = load_results()
        syn_matches = {e["src_ip"]: e["match"] for e in data if e["packet_type"] == "syn"}
        expected = {
            "10.0.1.10": "Linux:6.x",
            "10.0.2.20": "Windows:11",
            "10.0.3.30": "macOS:14.x",
            "10.0.4.40": "FreeBSD:14.x",
            "10.0.5.50": "Linux:6.x-ecn",
            "10.0.6.60": "OpenBSD:7.x",
            "10.0.7.70": "unknown",
            "10.0.8.80": "Linux:6.x-ipopt",
        }
        assert syn_matches == expected, f"SYN match mismatch: {syn_matches}"

    def test_response_section_labels_correct(self):
        """Verify all tcp:response matches come from correct OS labels."""
        data = load_results()
        sa_matches = {e["dst_ip"]: e["match"] for e in data if e["packet_type"] == "syn+ack"}
        expected = {
            "10.0.1.10": "Linux:6.x",
            "10.0.2.20": "Windows:Server",
            "10.0.3.30": "Linux:6.x-ecn",
            "10.0.4.40": "FreeBSD:14.x",
        }
        assert sa_matches == expected, f"SYN+ACK match mismatch: {sa_matches}"

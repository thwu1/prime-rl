"""Tests for TCP passive OS fingerprinting engine.

Verifies that the fingerprinting tool correctly parses PCAP packets,
extracts p0f-format signatures, and matches against the signature database.
"""

import json
import os
import pytest


RESULTS_FILE = "/app/results.json"

# Expected results for all 8 SYN packets (packet index 8 is a SYN-ACK distractor)
EXPECTED = [
    {
        "packet_index": 0,
        "src_ip": "10.0.1.10",
        "dst_ip": "192.168.1.1",
        "src_port": 49152,
        "dst_port": 80,
        "signature": "4:64:0:1460:mss*20,7:mss,sok,ts,nop,ws:df,id+:0",
        "os_class": "linux",
        "os_name": "5.x",
    },
    {
        "packet_index": 1,
        "src_ip": "10.0.2.20",
        "dst_ip": "192.168.1.1",
        "src_port": 49200,
        "dst_port": 443,
        "signature": "4:128:0:1460:8192,8:mss,nop,ws,nop,nop,sok:df,id+:0",
        "os_class": "win",
        "os_name": "10",
    },
    {
        "packet_index": 2,
        "src_ip": "10.0.3.30",
        "dst_ip": "192.168.1.1",
        "src_port": 49300,
        "dst_port": 80,
        "signature": "4:64:0:1460:65535,6:mss,nop,ws,nop,nop,ts,sok,eol+1:df,id+:0",
        "os_class": "osx",
        "os_name": "12.x",
    },
    {
        "packet_index": 3,
        "src_ip": "10.0.4.40",
        "dst_ip": "192.168.1.1",
        "src_port": 49400,
        "dst_port": 443,
        "signature": "4:64:0:1460:65535,6:mss,nop,ws,sok,ts:df:0",
        "os_class": "freebsd",
        "os_name": "13.x",
    },
    {
        "packet_index": 4,
        "src_ip": "10.0.5.50",
        "dst_ip": "192.168.1.1",
        "src_port": 49500,
        "dst_port": 80,
        "signature": "4:64:0:1460:mss*20,7:mss,sok,ts,nop,ws:df,id+,ecn:0",
        "os_class": "linux",
        "os_name": "4.x:ecn",
    },
    {
        "packet_index": 5,
        "src_ip": "10.0.6.60",
        "dst_ip": "192.168.1.1",
        "src_port": 49600,
        "dst_port": 80,
        "signature": "4:128:0:1460:8192,8:mss,nop,ws,sok,ts:df,id+:0",
        "os_class": "win",
        "os_name": "server2019",
    },
    {
        "packet_index": 6,
        "src_ip": "10.0.7.70",
        "dst_ip": "192.168.1.1",
        "src_port": 49700,
        "dst_port": 443,
        "signature": "4:64:0:1460:16384,0:mss,nop,nop,sok,nop,ws,nop,nop,ts:df:0",
        "os_class": "openbsd",
        "os_name": "7.x",
    },
    {
        "packet_index": 7,
        "src_ip": "10.0.8.80",
        "dst_ip": "192.168.1.1",
        "src_port": 49800,
        "dst_port": 80,
        "signature": "4:255:0:1460:mss*34,0:nop,nop,ts,mss,nop,ws,sok,eol+1::0",
        "os_class": "solaris",
        "os_name": "11",
    },
]


@pytest.fixture(scope="session")
def results():
    """Load the results JSON file."""
    if not os.path.exists(RESULTS_FILE):
        pytest.fail(f"{RESULTS_FILE} does not exist — fingerprint tool did not produce output")
    with open(RESULTS_FILE) as f:
        return json.load(f)


class TestBasicStructure:
    """Verify the output file has the correct structure."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_FILE), "results.json was not created"

    def test_results_is_list(self, results):
        assert isinstance(results, list), "results.json must contain a JSON array"

    def test_packet_count(self, results):
        assert len(results) == 8, (
            f"Expected 8 SYN packets in results (PCAP has 9 packets, "
            f"1 SYN-ACK must be filtered), got {len(results)}"
        )

    def test_required_fields(self, results):
        required = {"packet_index", "src_ip", "dst_ip", "src_port",
                     "dst_port", "signature", "os_class", "os_name"}
        for i, r in enumerate(results):
            missing = required - set(r.keys())
            assert not missing, f"Result {i} missing fields: {missing}"


class TestSignatureExtraction:
    """Verify correct p0f signature extraction for each packet."""

    @pytest.mark.parametrize("idx", range(8))
    def test_signature(self, results, idx):
        expected_sig = EXPECTED[idx]["signature"]
        actual_sig = results[idx]["signature"]
        assert actual_sig == expected_sig, (
            f"Packet {idx} ({EXPECTED[idx]['os_class']}:{EXPECTED[idx]['os_name']}): "
            f"expected signature '{expected_sig}', got '{actual_sig}'"
        )


class TestOSIdentification:
    """Verify correct OS identification from database matching."""

    @pytest.mark.parametrize("idx", range(8))
    def test_os_class(self, results, idx):
        expected_class = EXPECTED[idx]["os_class"]
        actual_class = results[idx]["os_class"]
        assert actual_class == expected_class, (
            f"Packet {idx}: expected os_class '{expected_class}', got '{actual_class}'"
        )

    @pytest.mark.parametrize("idx", range(8))
    def test_os_name(self, results, idx):
        expected_name = EXPECTED[idx]["os_name"]
        actual_name = results[idx]["os_name"]
        assert actual_name == expected_name, (
            f"Packet {idx}: expected os_name '{expected_name}', got '{actual_name}'"
        )


class TestNetworkMetadata:
    """Verify correct parsing of IP addresses and ports."""

    @pytest.mark.parametrize("idx", range(8))
    def test_src_ip(self, results, idx):
        assert results[idx]["src_ip"] == EXPECTED[idx]["src_ip"]

    @pytest.mark.parametrize("idx", range(8))
    def test_dst_ip(self, results, idx):
        assert results[idx]["dst_ip"] == EXPECTED[idx]["dst_ip"]

    @pytest.mark.parametrize("idx", range(8))
    def test_src_port(self, results, idx):
        assert results[idx]["src_port"] == EXPECTED[idx]["src_port"]

    @pytest.mark.parametrize("idx", range(8))
    def test_dst_port(self, results, idx):
        assert results[idx]["dst_port"] == EXPECTED[idx]["dst_port"]

    @pytest.mark.parametrize("idx", range(8))
    def test_packet_index(self, results, idx):
        assert results[idx]["packet_index"] == EXPECTED[idx]["packet_index"]


class TestTTLGuessing:
    """Verify initial TTL is correctly guessed from observed TTL."""

    def test_ttl_62_guesses_64(self, results):
        """Observed TTL=62 (Linux) should guess initial TTL=64."""
        sig = results[0]["signature"]
        ittl = sig.split(":")[1]
        assert ittl == "64", f"TTL 62 should guess 64, got {ittl}"

    def test_ttl_125_guesses_128(self, results):
        """Observed TTL=125 (Windows) should guess initial TTL=128."""
        sig = results[1]["signature"]
        ittl = sig.split(":")[1]
        assert ittl == "128", f"TTL 125 should guess 128, got {ittl}"

    def test_ttl_253_guesses_255(self, results):
        """Observed TTL=253 (Solaris) should guess initial TTL=255."""
        sig = results[7]["signature"]
        ittl = sig.split(":")[1]
        assert ittl == "255", f"TTL 253 should guess 255, got {ittl}"

    def test_ttl_64_stays_64(self, results):
        """Observed TTL=64 (FreeBSD) should guess initial TTL=64."""
        sig = results[3]["signature"]
        ittl = sig.split(":")[1]
        assert ittl == "64", f"TTL 64 should stay 64, got {ittl}"

    def test_ttl_61_guesses_64(self, results):
        """Observed TTL=61 (OpenBSD) should guess initial TTL=64."""
        sig = results[6]["signature"]
        ittl = sig.split(":")[1]
        assert ittl == "64", f"TTL 61 should guess 64, got {ittl}"


class TestWindowClassification:
    """Verify window size is correctly classified."""

    def test_mss_multiple_detected(self, results):
        """Window 29200 = 1460*20 should be classified as mss*20."""
        sig = results[0]["signature"]
        wsize_scale = sig.split(":")[4]
        assert wsize_scale.startswith("mss*20"), (
            f"Window 29200 with MSS 1460 should be mss*20, got {wsize_scale}"
        )

    def test_absolute_window(self, results):
        """Window 8192 should remain absolute (not mss*N or mtu*N)."""
        sig = results[1]["signature"]
        wsize_scale = sig.split(":")[4]
        assert wsize_scale.startswith("8192"), (
            f"Window 8192 should be absolute, got {wsize_scale}"
        )

    def test_mss_multiple_solaris(self, results):
        """Window 49640 = 1460*34 should be classified as mss*34."""
        sig = results[7]["signature"]
        wsize_scale = sig.split(":")[4]
        assert wsize_scale.startswith("mss*34"), (
            f"Window 49640 with MSS 1460 should be mss*34, got {wsize_scale}"
        )

    def test_large_absolute_window(self, results):
        """Window 65535 should remain absolute."""
        sig = results[2]["signature"]
        wsize_scale = sig.split(":")[4]
        assert wsize_scale.startswith("65535"), (
            f"Window 65535 should be absolute, got {wsize_scale}"
        )


class TestQuirkDetection:
    """Verify quirk flags are correctly detected."""

    def test_ecn_detected(self, results):
        """Packet 4 (Linux ECN) should have ecn quirk."""
        quirks = results[4]["signature"].split(":")[6]
        assert "ecn" in quirks, f"ECN not detected in packet 4 quirks: {quirks}"

    def test_ecn_not_false_positive(self, results):
        """Packet 0 (Linux 5.x) should NOT have ecn quirk."""
        quirks = results[0]["signature"].split(":")[6]
        assert "ecn" not in quirks, f"False ECN in packet 0 quirks: {quirks}"

    def test_df_present(self, results):
        """Packets with DF flag should have df quirk."""
        for idx in [0, 1, 2, 3, 4, 5, 6]:
            quirks = results[idx]["signature"].split(":")[6]
            assert "df" in quirks, f"Packet {idx} missing df quirk: {quirks}"

    def test_df_absent_solaris(self, results):
        """Solaris packet (no DF) should NOT have df quirk."""
        quirks = results[7]["signature"].split(":")[6]
        assert "df" not in quirks, f"Solaris should not have df quirk: {quirks}"

    def test_id_plus_with_df(self, results):
        """Packets with DF and non-zero IP ID should have id+ quirk."""
        for idx in [0, 1, 2, 4, 5]:
            quirks = results[idx]["signature"].split(":")[6]
            assert "id+" in quirks, f"Packet {idx} missing id+ quirk: {quirks}"

    def test_no_id_plus_zero_id(self, results):
        """Packets with DF but zero IP ID should NOT have id+ quirk."""
        for idx in [3, 6]:  # FreeBSD and OpenBSD have ID=0
            quirks = results[idx]["signature"].split(":")[6]
            assert "id+" not in quirks, (
                f"Packet {idx} should not have id+ (zero IP ID): {quirks}"
            )


class TestEOLPadding:
    """Verify EOL option and padding byte counting."""

    def test_eol_macos(self, results):
        """macOS packet should have eol+1 in options layout."""
        olayout = results[2]["signature"].split(":")[5]
        assert "eol+1" in olayout, f"macOS missing eol+1 in layout: {olayout}"

    def test_eol_solaris(self, results):
        """Solaris packet should have eol+1 in options layout."""
        olayout = results[7]["signature"].split(":")[5]
        assert "eol+1" in olayout, f"Solaris missing eol+1 in layout: {olayout}"

    def test_no_eol_linux(self, results):
        """Linux packet should NOT have eol in options layout."""
        olayout = results[0]["signature"].split(":")[5]
        assert "eol" not in olayout, f"Linux should not have eol: {olayout}"

    def test_no_eol_windows(self, results):
        """Windows packet should NOT have eol in options layout."""
        olayout = results[1]["signature"].split(":")[5]
        assert "eol" not in olayout, f"Windows should not have eol: {olayout}"


class TestOptionLayouts:
    """Verify TCP option parsing produces correct layouts for distinct OS signatures."""

    def test_linux_layout(self, results):
        olayout = results[0]["signature"].split(":")[5]
        assert olayout == "mss,sok,ts,nop,ws", f"Linux layout wrong: {olayout}"

    def test_windows_layout(self, results):
        olayout = results[1]["signature"].split(":")[5]
        assert olayout == "mss,nop,ws,nop,nop,sok", f"Windows layout wrong: {olayout}"

    def test_openbsd_layout(self, results):
        olayout = results[6]["signature"].split(":")[5]
        assert olayout == "mss,nop,nop,sok,nop,ws,nop,nop,ts", (
            f"OpenBSD layout wrong: {olayout}"
        )

    def test_solaris_layout(self, results):
        olayout = results[7]["signature"].split(":")[5]
        assert olayout == "nop,nop,ts,mss,nop,ws,sok,eol+1", (
            f"Solaris layout wrong: {olayout}"
        )

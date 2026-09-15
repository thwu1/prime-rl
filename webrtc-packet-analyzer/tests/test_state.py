#!/usr/bin/env python3
"""Tests for the WebRTC multi-capture forensic analyzer."""

import json
import os
import subprocess
import pytest


@pytest.fixture(scope="session")
def report():
    report_path = "/app/report.json"
    assert os.path.exists(report_path), "report.json not found at /app/report.json"
    with open(report_path) as f:
        data = json.load(f)
    return data


def _capinfos_packet_count(filepath):
    """Extract packet count from a capture file using capinfos."""
    result = subprocess.run(
        ['capinfos', '-c', filepath],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return -1
    for line in result.stdout.split('\n'):
        if 'Number of packets' in line:
            return int(line.split(':')[1].strip())
    return -1


class TestMergedPcap:
    def test_merged_pcap_exists(self):
        assert os.path.exists("/app/merged.pcap"), \
            "merged.pcap must exist at /app/merged.pcap"

    def test_merged_pcap_is_valid_capture(self):
        result = subprocess.run(
            ['capinfos', '-c', '/app/merged.pcap'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            "merged.pcap is not a valid capture file"

    def test_merged_pcap_packet_count(self):
        count = _capinfos_packet_count("/app/merged.pcap")
        assert count == 80, \
            f"Expected 80 packets in merged.pcap, got {count}"


class TestCaptureInfo:
    def test_alpha_packets(self, report):
        assert report["capture_info"]["tap_alpha_packets"] == 6

    def test_beta_packets(self, report):
        assert report["capture_info"]["tap_beta_packets"] == 74

    def test_merged_total(self, report):
        assert report["capture_info"]["merged_total_packets"] == 80

    def test_capture_duration(self, report):
        assert abs(report["capture_info"]["capture_duration_sec"] - 2.06) < 0.01, \
            f"Expected duration ~2.06s, got {report['capture_info']['capture_duration_sec']}"


class TestSessionIntegrity:
    def test_hmac_valid(self, report):
        assert report["session_integrity"]["config_hmac_valid"] is True, \
            "HMAC verification should pass for untampered config"


class TestPacketCounts:
    def test_total(self, report):
        assert report["packet_counts"]["total"] == 80

    def test_stun(self, report):
        assert report["packet_counts"]["stun"] == 5

    def test_dtls(self, report):
        assert report["packet_counts"]["dtls"] == 3

    def test_rtp(self, report):
        assert report["packet_counts"]["rtp"] == 67

    def test_rtcp(self, report):
        assert report["packet_counts"]["rtcp"] == 4

    def test_unknown(self, report):
        assert report["packet_counts"]["unknown"] == 1


class TestStunAnalysis:
    def test_binding_requests(self, report):
        assert report["stun_analysis"]["binding_requests"] == 3

    def test_binding_responses(self, report):
        assert report["stun_analysis"]["binding_responses"] == 2

    def test_integrity_valid(self, report):
        assert report["stun_analysis"]["integrity_valid"] == 4

    def test_integrity_invalid(self, report):
        assert report["stun_analysis"]["integrity_invalid"] == 1

    def test_nominated_pair_src(self, report):
        assert report["stun_analysis"]["nominated_pair"]["src"] == "10.0.0.1:50000"

    def test_nominated_pair_dst(self, report):
        assert report["stun_analysis"]["nominated_pair"]["dst"] == "10.0.0.2:50001"


class TestRtpAnalysisAudio:
    """Tests for audio SSRC 0x12345678."""

    def test_ssrc_present(self, report):
        assert "0x12345678" in report["rtp_analysis"]

    def test_packet_count(self, report):
        stats = report["rtp_analysis"]["0x12345678"]
        assert stats["packet_count"] == 45

    def test_loss_count(self, report):
        stats = report["rtp_analysis"]["0x12345678"]
        assert stats["loss_count"] == 5

    def test_loss_rate(self, report):
        stats = report["rtp_analysis"]["0x12345678"]
        assert abs(stats["loss_rate"] - 0.1) < 0.001

    def test_jitter(self, report):
        stats = report["rtp_analysis"]["0x12345678"]
        # Jitter should be approximately 14.54 RTP timestamp units
        assert abs(stats["jitter"] - 14.54) < 0.5, \
            f"Jitter {stats['jitter']} not within 0.5 of expected 14.54"

    def test_duration(self, report):
        stats = report["rtp_analysis"]["0x12345678"]
        assert abs(stats["duration_ms"] - 979.95) < 1.0

    def test_first_seq(self, report):
        stats = report["rtp_analysis"]["0x12345678"]
        assert stats["first_seq"] == 1000

    def test_last_seq(self, report):
        stats = report["rtp_analysis"]["0x12345678"]
        assert stats["last_seq"] == 1049


class TestRtpAnalysisVideo:
    """Tests for video SSRC 0xdeadbeef."""

    def test_ssrc_present(self, report):
        assert "0xdeadbeef" in report["rtp_analysis"]

    def test_packet_count(self, report):
        stats = report["rtp_analysis"]["0xdeadbeef"]
        assert stats["packet_count"] == 22

    def test_loss_count(self, report):
        stats = report["rtp_analysis"]["0xdeadbeef"]
        assert stats["loss_count"] == 3

    def test_loss_rate(self, report):
        stats = report["rtp_analysis"]["0xdeadbeef"]
        assert abs(stats["loss_rate"] - 0.12) < 0.001

    def test_jitter(self, report):
        stats = report["rtp_analysis"]["0xdeadbeef"]
        # Jitter should be approximately 36.05 RTP timestamp units
        assert abs(stats["jitter"] - 36.05) < 0.5, \
            f"Jitter {stats['jitter']} not within 0.5 of expected 36.05"

    def test_duration(self, report):
        stats = report["rtp_analysis"]["0xdeadbeef"]
        assert abs(stats["duration_ms"] - 800.192) < 1.0

    def test_first_seq(self, report):
        stats = report["rtp_analysis"]["0xdeadbeef"]
        assert stats["first_seq"] == 5000

    def test_last_seq(self, report):
        stats = report["rtp_analysis"]["0xdeadbeef"]
        assert stats["last_seq"] == 5024


class TestRtpSsrcCount:
    def test_exactly_two_ssrcs(self, report):
        assert len(report["rtp_analysis"]) == 2


class TestRtcpAnalysis:
    def test_sender_reports(self, report):
        assert report["rtcp_analysis"]["sender_reports"] == 3

    def test_receiver_reports(self, report):
        assert report["rtcp_analysis"]["receiver_reports"] == 1


class TestReportStructure:
    def test_top_level_keys(self, report):
        required = {"capture_info", "session_integrity", "packet_counts",
                     "stun_analysis", "rtp_analysis", "rtcp_analysis"}
        assert required.issubset(set(report.keys()))

    def test_capture_info_keys(self, report):
        required = {"tap_alpha_packets", "tap_beta_packets",
                     "merged_total_packets", "capture_duration_sec"}
        assert required.issubset(set(report["capture_info"].keys()))

    def test_session_integrity_keys(self, report):
        required = {"config_hmac_valid"}
        assert required.issubset(set(report["session_integrity"].keys()))

    def test_packet_counts_keys(self, report):
        required = {"total", "stun", "dtls", "rtp", "rtcp", "unknown"}
        assert required.issubset(set(report["packet_counts"].keys()))

    def test_stun_analysis_keys(self, report):
        required = {"binding_requests", "binding_responses", "integrity_valid",
                     "integrity_invalid", "nominated_pair"}
        assert required.issubset(set(report["stun_analysis"].keys()))

    def test_rtp_stats_keys(self, report):
        for ssrc, stats in report["rtp_analysis"].items():
            required = {"packet_count", "loss_count", "loss_rate", "jitter",
                        "duration_ms", "first_seq", "last_seq"}
            assert required.issubset(set(stats.keys())), \
                f"SSRC {ssrc} missing keys: {required - set(stats.keys())}"

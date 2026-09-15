"""
Verify TCP-AO forensic audit report against known ground truth.

"""

import json
import pytest


EXPECTED = {
    # Authentic packets: verdict, computed_mac (from RFC 9235 test vectors)
    "pkt_01": {
        "verdict": "authentic",
        "computed_mac": "2ee437c6f8ede6d7c4d602e7",
        "attack_class": None,
    },
    "pkt_02": {
        "verdict": "authentic",
        "computed_mac": "97766e48ac262de9ae61b4f9",
        "attack_class": None,
    },
    "pkt_03": {
        "verdict": "authentic",
        "computed_mac": "77412742fa4dc433eff0973e",
        "attack_class": None,
    },
    "pkt_04": {
        "verdict": "authentic",
        "computed_mac": "f1cba346c3526163f71f1f55",
        "attack_class": None,
    },
    "pkt_05": {
        "verdict": "authentic",
        "computed_mac": "59b588107481ac6dc3927040",
        "attack_class": None,
    },
    "pkt_06": {
        "verdict": "authentic",
        "computed_mac": "1d01f6c87c6f93acffa9d4b5",
        "attack_class": None,
    },
    # Forged packets: verdict, attack_class, and known values where applicable
    "pkt_07": {
        "verdict": "forged",
        "attack_class": "wrong_coverage",
        "packet_mac": "eeab0fe24c3010815116b3be",
    },
    "pkt_08": {
        "verdict": "forged",
        "attack_class": "wrong_coverage",
        "packet_mac": "7b6a455c0d4f5f01835baab3",
    },
    "pkt_09": {
        "verdict": "forged",
        "attack_class": "corrupted_mac",
        "computed_mac": "e477e99c8040765498e55091",
        "packet_mac": "e477e99c8040765498e55192",
    },
    "pkt_10": {
        "verdict": "forged",
        "attack_class": "corrupted_mac",
        "computed_mac": "885698b0530ed4d5a15f8346",
        "packet_mac": "885698b0530ed4d5a15f8247",
    },
    "pkt_11": {
        "verdict": "forged",
        "attack_class": "modified_payload",
        "packet_mac": "a63f0ecbbb2e635c954deac7",
    },
    "pkt_12": {
        "verdict": "forged",
        "attack_class": "modified_payload",
        "packet_mac": "290cf414ccb47a333276e7f8",
    },
}


@pytest.fixture
def report():
    with open("/app/audit_report.json") as f:
        return json.load(f)


def test_report_contains_all_12_packets(report):
    """The report must have entries for all 12 packet IDs."""
    for pid in EXPECTED:
        assert pid in report, f"Missing packet {pid} in audit report"
    assert len(report) == 12, f"Expected 12 entries, got {len(report)}"


def test_verdicts_correct(report):
    """Every packet must have the correct authentic/forged verdict."""
    for pid, exp in EXPECTED.items():
        actual = report[pid]["verdict"]
        assert actual == exp["verdict"], (
            f"{pid}: expected verdict '{exp['verdict']}', got '{actual}'"
        )


def test_authentic_computed_macs(report):
    """Authentic packets must have the correctly computed MAC (proves KDF+MAC implementation)."""
    for pid in ["pkt_01", "pkt_02", "pkt_03", "pkt_04", "pkt_05", "pkt_06"]:
        exp_mac = EXPECTED[pid]["computed_mac"]
        actual = report[pid]["computed_mac"]
        assert actual == exp_mac, (
            f"{pid}: expected computed_mac '{exp_mac}', got '{actual}'"
        )


def test_authentic_mac_match(report):
    """For authentic packets, computed_mac and packet_mac must be identical."""
    for pid in ["pkt_01", "pkt_02", "pkt_03", "pkt_04", "pkt_05", "pkt_06"]:
        r = report[pid]
        assert r["computed_mac"] == r["packet_mac"], (
            f"{pid}: authentic packet should have computed_mac == packet_mac"
        )


def test_authentic_null_attack_class(report):
    """Authentic packets must have null attack_class."""
    for pid in ["pkt_01", "pkt_02", "pkt_03", "pkt_04", "pkt_05", "pkt_06"]:
        ac = report[pid]["attack_class"]
        assert ac is None, f"{pid}: authentic should have null attack_class, got '{ac}'"


def test_forged_attack_classes(report):
    """Every forged packet must have the correct attack classification."""
    for pid in ["pkt_07", "pkt_08", "pkt_09", "pkt_10", "pkt_11", "pkt_12"]:
        exp_class = EXPECTED[pid]["attack_class"]
        actual = report[pid]["attack_class"]
        assert actual == exp_class, (
            f"{pid}: expected attack_class '{exp_class}', got '{actual}'"
        )


def test_forged_mac_mismatch(report):
    """For forged packets, computed_mac must differ from packet_mac."""
    for pid in ["pkt_07", "pkt_08", "pkt_09", "pkt_10", "pkt_11", "pkt_12"]:
        r = report[pid]
        assert r["computed_mac"] != r["packet_mac"], (
            f"{pid}: forged packet must have computed_mac != packet_mac"
        )


def test_corrupted_mac_known_values(report):
    """For corrupted_mac packets, verify exact computed and packet MACs."""
    for pid in ["pkt_09", "pkt_10"]:
        exp = EXPECTED[pid]
        r = report[pid]
        assert r["computed_mac"] == exp["computed_mac"], (
            f"{pid}: expected computed_mac '{exp['computed_mac']}', got '{r['computed_mac']}'"
        )
        assert r["packet_mac"] == exp["packet_mac"], (
            f"{pid}: expected packet_mac '{exp['packet_mac']}', got '{r['packet_mac']}'"
        )


def test_corrupted_mac_small_difference(report):
    """Corrupted MAC packets must have <= 3 bytes different between computed and packet MAC."""
    for pid in ["pkt_09", "pkt_10"]:
        r = report[pid]
        cm = bytes.fromhex(r["computed_mac"])
        pm = bytes.fromhex(r["packet_mac"])
        diff = sum(1 for a, b in zip(cm, pm) if a != b)
        assert diff <= 3, (
            f"{pid}: corrupted_mac should have <=3 byte differences, got {diff}"
        )


def test_modified_payload_packet_mac(report):
    """Modified payload packets must have the expected (original) packet MAC."""
    for pid in ["pkt_11", "pkt_12"]:
        exp_pm = EXPECTED[pid]["packet_mac"]
        actual = report[pid]["packet_mac"]
        assert actual == exp_pm, (
            f"{pid}: expected packet_mac '{exp_pm}', got '{actual}'"
        )


def test_modified_payload_large_mac_difference(report):
    """Modified payload: computed and packet MAC must differ by more than 3 bytes."""
    for pid in ["pkt_11", "pkt_12"]:
        r = report[pid]
        cm = bytes.fromhex(r["computed_mac"])
        pm = bytes.fromhex(r["packet_mac"])
        diff = sum(1 for a, b in zip(cm, pm) if a != b)
        assert diff > 3, (
            f"{pid}: modified_payload should have >3 byte differences, got {diff}"
        )


def test_wrong_coverage_packet_macs(report):
    """Wrong coverage packets must have the expected packet MAC from the original."""
    for pid in ["pkt_07", "pkt_08"]:
        exp_pm = EXPECTED[pid]["packet_mac"]
        actual = report[pid]["packet_mac"]
        assert actual == exp_pm, (
            f"{pid}: expected packet_mac '{exp_pm}', got '{actual}'"
        )


def test_report_field_presence(report):
    """Every entry must have all four required fields."""
    required = {"verdict", "computed_mac", "packet_mac", "attack_class"}
    for pid, entry in report.items():
        missing = required - set(entry.keys())
        assert not missing, f"{pid}: missing fields {missing}"

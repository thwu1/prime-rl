
"""Tests for HTB Traffic Shaping Forensics output."""

import json
import os
import subprocess

REPORT_PATH = "/app/forensic_report.json"
ETH0_CLASS_PATH = "/app/captures/eth0_class.txt"


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def test_report_exists():
    assert os.path.exists(REPORT_PATH), "forensic_report.json must exist at /app/"


def test_report_structure():
    report = load_report()
    assert isinstance(report, dict)
    assert "validation_errors" in report, "Report must contain validation_errors"
    assert "leaf_allocations" in report, "Report must contain leaf_allocations"
    assert "sla_violations" in report, "Report must contain sla_violations"
    assert "nft_mark_map" in report, "Report must contain nft_mark_map"


def test_validation_error_count():
    report = load_report()
    errors = report["validation_errors"]
    assert len(errors) >= 6, f"Expected at least 6 validation errors, got {len(errors)}"


def test_ceil_exceeds_parent_detected():
    """Class 2:12 has ceil=900Mbit but parent 2:10 has ceil=800Mbit."""
    report = load_report()
    errors = report["validation_errors"]
    found = any("2:12" in json.dumps(e) for e in errors)
    assert found, "Should detect that class 2:12 ceil (900) exceeds parent 2:10 ceil (800)"


def test_oversubscription_detected():
    """Class 2:20 children rates (200+150=350) exceed parent rate (300)."""
    report = load_report()
    errors = report["validation_errors"]
    found = any("2:20" in json.dumps(e) for e in errors)
    assert found, "Should detect rate oversubscription under class 2:20"


def test_orphan_class_detected():
    """Class 2:41 references parent 2:40 which does not exist."""
    report = load_report()
    errors = report["validation_errors"]
    found = any("2:41" in json.dumps(e) for e in errors)
    assert found, "Should detect orphan class 2:41 (parent 2:40 missing)"


def test_missing_default_class_detected():
    """Qdisc on eth1 has default 0x32 (=class 2:50) which does not exist."""
    report = load_report()
    errors = report["validation_errors"]
    found = any("2:50" in json.dumps(e) for e in errors)
    assert found, "Should detect missing default class 2:50 on eth1"


def test_invalid_filter_target_detected():
    """fw filter handle 0xf on eth0 maps to classid 1:45 which does not exist."""
    report = load_report()
    errors = report["validation_errors"]
    found = any("1:45" in json.dumps(e) for e in errors)
    assert found, "Should detect invalid filter target 1:45 on eth0"


def test_cross_tool_mark_mismatch():
    """nft sets mark 0xc for eth1 traffic but no tc fw filter for 0xc on eth1."""
    report = load_report()
    errors = report["validation_errors"]
    found = any(
        "0xc" in json.dumps(e) and "eth1" in json.dumps(e)
        for e in errors
    )
    assert found, "Should detect nft mark 0xc set for eth1 without matching tc filter"


def test_eth0_leaf_allocations():
    """Verify bandwidth allocation for all eth0 leaf classes."""
    report = load_report()
    alloc = report["leaf_allocations"]["eth0"]

    expected = {
        "1:11": 2250.0,
        "1:12": 1000.0,
        "1:13": 500.0,
        "1:21": 1625.0,
        "1:22": 1625.0,
        "1:23": 500.0,
        "1:31": 800.0,
        "1:32": 700.0,
        "1:33": 500.0,
        "1:99": 500.0,
    }

    for classid, expected_bw in expected.items():
        actual = alloc.get(classid)
        assert actual is not None, f"eth0 leaf {classid} missing from allocations"
        assert abs(actual - expected_bw) < 1.0, (
            f"eth0 {classid}: expected {expected_bw} Mbps, got {actual} Mbps"
        )


def test_eth0_total_allocation():
    """Total eth0 leaf allocation must equal root rate (10000 Mbps)."""
    report = load_report()
    alloc = report["leaf_allocations"]["eth0"]
    total = sum(alloc.values())
    assert abs(total - 10000) < 1.0, f"eth0 total should be 10000, got {total}"


def test_eth1_leaf_allocations():
    """Verify bandwidth allocation for all eth1 leaf classes."""
    report = load_report()
    alloc = report["leaf_allocations"]["eth1"]

    expected = {
        "2:11": 350.0,
        "2:12": 100.0,
        "2:21": 100.0,
        "2:22": 200.0,
        "2:31": 150.0,
        "2:32": 100.0,
    }

    for classid, expected_bw in expected.items():
        actual = alloc.get(classid)
        assert actual is not None, f"eth1 leaf {classid} missing from allocations"
        assert abs(actual - expected_bw) < 1.0, (
            f"eth1 {classid}: expected {expected_bw} Mbps, got {actual} Mbps"
        )


def test_eth1_total_allocation():
    """Total eth1 leaf allocation must equal root rate (1000 Mbps)."""
    report = load_report()
    alloc = report["leaf_allocations"]["eth1"]
    total = sum(alloc.values())
    assert abs(total - 1000) < 1.0, f"eth1 total should be 1000, got {total}"


def test_sla_violation_count():
    report = load_report()
    violations = report["sla_violations"]
    assert len(violations) == 2, f"Expected exactly 2 SLA violations, got {len(violations)}"


def test_sla_violation_classes():
    """1:31 (gets 800 < required 1000) and 2:21 (gets 100 < required 150)."""
    report = load_report()
    violations = report["sla_violations"]

    violation_classes = {v["class"] for v in violations}
    assert "1:31" in violation_classes, "Should identify 1:31 as SLA violation (800 < 1000)"
    assert "2:21" in violation_classes, "Should identify 2:21 as SLA violation (100 < 150)"


def test_nft_mark_map_eth0():
    """Verify nft-to-tc mark mapping for eth0."""
    report = load_report()
    mark_map = report["nft_mark_map"]["eth0"]
    expected = {
        "0xa": "1:11",
        "0xb": "1:12",
        "0xc": "1:21",
        "0xd": "1:31",
        "0xe": "1:32",
        "0xf": "1:45",
    }
    for mark, classid in expected.items():
        assert mark_map.get(mark) == classid, (
            f"eth0 mark {mark} should map to {classid}, got {mark_map.get(mark)}"
        )


def test_nft_mark_map_eth1():
    """Verify nft-to-tc mark mapping for eth1."""
    report = load_report()
    mark_map = report["nft_mark_map"]["eth1"]
    assert mark_map.get("0x14") == "2:11", "eth1 mark 0x14 should map to 2:11"
    assert mark_map.get("0x15") == "2:21", "eth1 mark 0x15 should map to 2:21"
    # Mark 0xc should NOT resolve on eth1 (no tc fw filter for it)
    assert "0xc" not in mark_map, (
        "Mark 0xc should not be in eth1 mark map (no tc filter for it on eth1)"
    )


def test_z_dynamic_computation():
    """Anti-cheat: modify raw tc class dump, re-run analyzer, verify output changes.

    When 1:30 rate changes from 2Gbit (2000 Mbps) to 3Gbit (3000 Mbps):
    - Root excess drops from 1500 to 500
    - 1:10 and 1:20 each get 3250 instead of 3750
    - 1:11 should get 1750 instead of 2250
    - 1:31 should get 1300 instead of 800
    """
    # Backup originals
    with open(REPORT_PATH) as f:
        original_report = f.read()
    with open(ETH0_CLASS_PATH) as f:
        original_class = f.read()

    try:
        # Modify tc class dump: increase 1:30 rate from 2Gbit to 3Gbit
        modified = original_class.replace(
            "class htb 1:30 parent 1:1 prio 1 quantum 3000 rate 2Gbit",
            "class htb 1:30 parent 1:1 prio 1 quantum 3000 rate 3Gbit",
        )
        assert modified != original_class, "Replacement should have changed the text"

        with open(ETH0_CLASS_PATH, "w") as f:
            f.write(modified)

        # Run analyzer on modified captures
        result = subprocess.run(
            ["python3", "/app/tc_forensic.py"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd="/app",
        )
        assert result.returncode == 0, f"Analyzer failed on modified input: {result.stderr}"

        # Load modified report
        with open(REPORT_PATH) as f:
            mod_report = json.load(f)

        mod_alloc = mod_report["leaf_allocations"]["eth0"]

        # With 1:30 rate=3000, root children sum=9500, excess=500
        # prio=0 classes 1:10,1:20 each get 250 excess -> 3250
        # 1:11 gets 1000 + (3250-2500) = 1750
        assert abs(mod_alloc["1:11"] - 1750) < 2.0, (
            f"Modified config: 1:11 should be ~1750, got {mod_alloc['1:11']}"
        )

        # 1:30 gets 3000, children sum 2000, excess 1000
        # prio=0: 1:31(q=1500) and 1:32(q=1500) each get 500 extra
        # 1:31 = 800+500 = 1300
        assert abs(mod_alloc["1:31"] - 1300) < 2.0, (
            f"Modified config: 1:31 should be ~1300, got {mod_alloc['1:31']}"
        )

        # Total must still be 10000
        total = sum(mod_alloc.values())
        assert abs(total - 10000) < 2.0, (
            f"Modified config: eth0 total should be 10000, got {total}"
        )
    finally:
        # Restore original captures and report
        with open(ETH0_CLASS_PATH, "w") as f:
            f.write(original_class)
        with open(REPORT_PATH, "w") as f:
            f.write(original_report)

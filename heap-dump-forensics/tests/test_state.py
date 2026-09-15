"""
Verification tests for heap forensics investigation and detection tool.

"""
import json
import os
import shutil
import struct
import subprocess
import tempfile

import pytest


EXPECTED_FLAG = "FLAG{tc4ch3_p01s0n_fd_f0r3ns1cs_a7e2b391}"
FLAG_PATH = "/app/flag.txt"
REPORT_PATH = "/app/forensic_report.txt"
CLEAN_DUMP = "/app/snapshot_clean.bin"
ATTACKED_DUMP = "/app/snapshot_attacked.bin"
BINARY_PATH = "/app/heapservice"
VALIDATOR_PATH = "/app/heap_validator.py"
HEAP_BASE = 0x55555555A000


def _protect_ptr(pos, ptr):
    """Replicate glibc PROTECT_PTR for test-generated snapshots."""
    return (pos >> 12) ^ ptr


# ────────────────────────────────────────────
#  Validator: existence and basic operation
# ────────────────────────────────────────────

def test_validator_exists():
    """The heap validator tool must exist."""
    assert os.path.isfile(VALIDATOR_PATH), f"Validator not found at {VALIDATOR_PATH}"


def test_validator_runs():
    """The validator must execute without crashing on the clean snapshot."""
    result = subprocess.run(
        ["python3", VALIDATOR_PATH, CLEAN_DUMP],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"Validator crashed: {result.stderr}"
    output = json.loads(result.stdout.strip())
    assert "compromised" in output, "Validator output must contain 'compromised' field"
    assert "poisoned_bins" in output, "Validator output must contain 'poisoned_bins' field"


# ────────────────────────────────────────────
#  Validator: correct classification
# ────────────────────────────────────────────

def test_validator_clean_snapshot():
    """Validator must identify the clean (pre-attack) snapshot as uncompromised."""
    result = subprocess.run(
        ["python3", VALIDATOR_PATH, CLEAN_DUMP],
        capture_output=True, text=True, timeout=30,
    )
    output = json.loads(result.stdout.strip())
    assert output["compromised"] is False, (
        f"Clean snapshot should be uncompromised, got: {output}"
    )


def test_validator_attacked_snapshot():
    """Validator must identify the attacked snapshot as compromised."""
    result = subprocess.run(
        ["python3", VALIDATOR_PATH, ATTACKED_DUMP],
        capture_output=True, text=True, timeout=30,
    )
    output = json.loads(result.stdout.strip())
    assert output["compromised"] is True, (
        f"Attacked snapshot should be compromised, got: {output}"
    )
    assert 3 in output["poisoned_bins"], (
        f"Validator should identify tcache bin 3 as poisoned, got bins: {output['poisoned_bins']}"
    )


def test_validator_target_address():
    """Validator must report the correct target address from the poisoned fd."""
    result = subprocess.run(
        ["python3", VALIDATOR_PATH, ATTACKED_DUMP],
        capture_output=True, text=True, timeout=30,
    )
    output = json.loads(result.stdout.strip())
    assert output["target_address"] is not None, "Validator must report a target address"
    target = int(output["target_address"], 16)
    expected_target = HEAP_BASE + 0x550  # chunk 7 userdata
    assert target == expected_target, (
        f"Target address 0x{target:x} != expected 0x{expected_target:x}"
    )


# ────────────────────────────────────────────
#  Validator: anti-hardcoding (novel snapshots)
# ────────────────────────────────────────────

def test_validator_benign_frees_only():
    """Validator must correctly classify a novel snapshot with only legitimate frees as clean."""
    with open(CLEAN_DUMP, "rb") as f:
        data = bytearray(f.read())

    tcache_key = HEAP_BASE + 0x010

    # Free chunk 4 (offset 0x3F0, chunk_size 0x70) into tcache bin 5 — legitimate
    struct.pack_into("<H", data, 0x010 + 5 * 2, 1)  # count[5] = 1
    struct.pack_into("<Q", data, 0x090 + 5 * 8, HEAP_BASE + 0x400)  # entries[5]
    chunk4_ud = HEAP_BASE + 0x400
    struct.pack_into("<Q", data, 0x400, _protect_ptr(chunk4_ud, 0))  # fd -> NULL
    struct.pack_into("<Q", data, 0x408, tcache_key)  # tcache key

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(bytes(data))
        temp_path = f.name

    try:
        result = subprocess.run(
            ["python3", VALIDATOR_PATH, temp_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Validator crashed: {result.stderr}"
        output = json.loads(result.stdout.strip())
        assert output["compromised"] is False, (
            f"Snapshot with only benign frees should be clean, got: {output}"
        )
    finally:
        os.unlink(temp_path)


def test_validator_novel_poisoning():
    """Validator must detect poisoning in a novel snapshot targeting a different bin and chunk."""
    with open(CLEAN_DUMP, "rb") as f:
        data = bytearray(f.read())

    tcache_key = HEAP_BASE + 0x010

    # Free chunk 6 (offset 0x510, chunk_size 0x30) into tcache bin 1
    struct.pack_into("<H", data, 0x010 + 1 * 2, 1)  # count[1] = 1
    struct.pack_into("<Q", data, 0x090 + 1 * 8, HEAP_BASE + 0x520)  # entries[1]
    chunk6_ud = HEAP_BASE + 0x520
    # POISON: fd points to chunk 0 userdata (allocated, not freed)
    poison_target = HEAP_BASE + 0x2A0
    struct.pack_into("<Q", data, 0x520, _protect_ptr(chunk6_ud, poison_target))
    struct.pack_into("<Q", data, 0x528, tcache_key)

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(bytes(data))
        temp_path = f.name

    try:
        result = subprocess.run(
            ["python3", VALIDATOR_PATH, temp_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Validator crashed: {result.stderr}"
        output = json.loads(result.stdout.strip())
        assert output["compromised"] is True, (
            f"Validator should detect novel tcache poisoning, got: {output}"
        )
        assert 1 in output["poisoned_bins"], (
            f"Validator should identify bin 1 as poisoned, got: {output['poisoned_bins']}"
        )
    finally:
        os.unlink(temp_path)


# ────────────────────────────────────────────
#  Flag verification
# ────────────────────────────────────────────

def test_flag_file_exists():
    """The flag file must exist at the expected path."""
    assert os.path.isfile(FLAG_PATH), f"Flag file not found at {FLAG_PATH}"


def test_flag_value():
    """The flag file must contain the exact correct decrypted token."""
    with open(FLAG_PATH, "r") as f:
        content = f.read().strip()
    assert content == EXPECTED_FLAG, f"Flag mismatch: got '{content}'"


def test_flag_format():
    """The flag must have the correct FLAG{{...}} format."""
    with open(FLAG_PATH, "r") as f:
        content = f.read().strip()
    assert content.startswith("FLAG{"), "Flag must start with 'FLAG{'"
    assert content.endswith("}"), "Flag must end with '}'"
    inner = content[5:-1]
    assert len(inner) > 0, "Flag content must not be empty"


# ────────────────────────────────────────────
#  Anti-cheat: flag must not be plaintext
# ────────────────────────────────────────────

def test_flag_not_in_clean_dump():
    """The plaintext flag must not appear in the clean heap snapshot."""
    with open(CLEAN_DUMP, "rb") as f:
        dump = f.read()
    assert EXPECTED_FLAG.encode() not in dump
    assert EXPECTED_FLAG[5:-1].encode() not in dump


def test_flag_not_in_attacked_dump():
    """The plaintext flag must not appear in the attacked heap snapshot."""
    with open(ATTACKED_DUMP, "rb") as f:
        dump = f.read()
    assert EXPECTED_FLAG.encode() not in dump
    assert EXPECTED_FLAG[5:-1].encode() not in dump


def test_flag_not_in_binary():
    """The plaintext flag must not appear in the stripped binary."""
    with open(BINARY_PATH, "rb") as f:
        binary = f.read()
    assert EXPECTED_FLAG.encode() not in binary


# ────────────────────────────────────────────
#  Forensic report verification
# ────────────────────────────────────────────

def test_report_exists():
    """The forensic report must exist."""
    assert os.path.isfile(REPORT_PATH), f"Forensic report not found at {REPORT_PATH}"


def test_report_substantial():
    """The forensic report must contain meaningful analysis (>500 chars)."""
    with open(REPORT_PATH, "r") as f:
        content = f.read()
    assert len(content) > 500, (
        f"Report is too short ({len(content)} chars) to contain meaningful analysis"
    )


def test_report_has_both_classifications():
    """The report must contain both BENIGN and MALICIOUS classifications."""
    with open(REPORT_PATH, "r") as f:
        content = f.read().upper()
    assert "MALICIOUS" in content, "Report must classify at least one change as MALICIOUS"
    assert "BENIGN" in content, "Report must classify at least one change as BENIGN"


def test_report_identifies_poisoned_chunk():
    """The report must identify the poisoned chunk and label it MALICIOUS."""
    with open(REPORT_PATH, "r") as f:
        content = f.read()

    content_lower = content.lower()

    poisoned_indicators = [
        "0x350", "0x360", "chunk 2", "chunk_2", "chunk2",
        "buffer_a", "buffer a", "slot 2", "slot2",
    ]

    has_indicator = any(ind.lower() in content_lower for ind in poisoned_indicators)
    has_malicious = "malicious" in content_lower

    assert has_indicator and has_malicious, (
        "Report must identify the poisoned chunk "
        "(chunk 2 / offset 0x350 or 0x360 / buffer_a) and classify it as MALICIOUS"
    )


def test_report_multiple_classifications():
    """The report must classify at least 3 distinct heap changes."""
    with open(REPORT_PATH, "r") as f:
        content = f.read().upper()

    benign_count = content.count("BENIGN")
    malicious_count = content.count("MALICIOUS")
    total = benign_count + malicious_count

    assert total >= 3, (
        f"Report should classify at least 3 changes, found {total} "
        f"({benign_count} benign + {malicious_count} malicious)"
    )


def test_report_has_benign_frees():
    """The report must acknowledge that some frees are legitimate."""
    with open(REPORT_PATH, "r") as f:
        content = f.read().upper()

    benign_count = content.count("BENIGN")
    assert benign_count >= 2, (
        f"Report should classify at least 2 changes as BENIGN, found {benign_count}"
    )


def test_report_impact_assessment():
    """The report must include an attack impact assessment with severity rating."""
    with open(REPORT_PATH, "r") as f:
        content = f.read()

    content_upper = content.upper()

    # Must have an impact/assessment section
    has_impact = "IMPACT" in content_upper or "ASSESSMENT" in content_upper
    assert has_impact, "Report must include an ATTACK IMPACT ASSESSMENT section"

    # Must include a severity rating
    severity_levels = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    has_severity = any(level in content_upper for level in severity_levels)
    assert has_severity, (
        "Report must include a severity rating (CRITICAL/HIGH/MEDIUM/LOW)"
    )

    # Must discuss the target data
    content_lower = content.lower()
    has_target = any(
        term in content_lower
        for term in ["session", "token", "credential", "secret"]
    )
    assert has_target, (
        "Impact assessment must discuss what sensitive data was at risk"
    )

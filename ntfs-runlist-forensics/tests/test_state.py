
"""
Verification tests for NTFS disk recovery methodology design task.

Tests independently parse the repaired output files and verify correctness
against hardcoded expected values. Includes forensic evaluation checks and
validation methodology assessment.
"""

import struct
import json
import os
import pytest

OUTPUT_DIR = "/app/output"

# Expected correct runlist: [(length_clusters, absolute_lcn), ...]
EXPECTED_RUNLIST = [
    (0x2800, 0x30000),
    (0x3200, 0x78000),
    (0x1E00, 0x2000000),
]
EXPECTED_HIGHEST_VCN = 0x77FF
EXPECTED_TOTAL_CLUSTERS = 0x7800
EXPECTED_TOTAL_SECTORS = 658505728
CORRECT_RECORD_OFFSET = 0x7000
DECEPTIVE_RECORD_OFFSET = 0x4000
CORRUPTED_RECORD_OFFSET = 0x1000
QUASI_VALID_OFFSET = 0x9000


def read_file(path):
    with open(path, 'rb') as f:
        return f.read()


def decode_mapping_pairs(data, start=0):
    """Decode NTFS mapping pairs to [(length, abs_lcn), ...]."""
    runs = []
    prev_lcn = 0
    i = start
    while i < len(data):
        hdr = data[i]
        if hdr == 0:
            break
        i += 1
        l_sz = hdr & 0x0F
        d_sz = (hdr >> 4) & 0x0F
        if l_sz == 0 or d_sz == 0:
            break
        if i + l_sz + d_sz > len(data):
            break
        length = int.from_bytes(data[i:i + l_sz], 'little')
        i += l_sz
        delta = int.from_bytes(data[i:i + d_sz], 'little', signed=True)
        i += d_sz
        lcn = prev_lcn + delta
        prev_lcn = lcn
        runs.append((length, lcn))
    return runs


def find_data_attr(data):
    """Find offset of $DATA attribute (type 0x80) in MFT entry."""
    if len(data) < 0x38:
        return None
    first = struct.unpack_from('<H', data, 0x14)[0]
    off = first
    while off < len(data) - 8:
        t = struct.unpack_from('<I', data, off)[0]
        if t == 0xFFFFFFFF:
            return None
        al = struct.unpack_from('<I', data, off + 4)[0]
        if al == 0 or al > len(data) - off:
            return None
        if t == 0x80:
            return off
        off += al
    return None


def _parse_offset(val):
    """Accept integer or hex-string offset values from JSON."""
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return int(val, 0)
    return val


# ==================== MFT entry tests ====================

def test_repaired_mft_exists():
    p = os.path.join(OUTPUT_DIR, "repaired_mft_entry.bin")
    assert os.path.isfile(p), f"Missing {p}"
    d = read_file(p)
    assert len(d) == 1024, f"MFT entry must be 1024 bytes, got {len(d)}"


def test_repaired_mft_signature():
    d = read_file(os.path.join(OUTPUT_DIR, "repaired_mft_entry.bin"))
    assert d[:4] == b'FILE', "MFT entry must start with 'FILE' signature"


def test_repaired_mft_runlist_count():
    d = read_file(os.path.join(OUTPUT_DIR, "repaired_mft_entry.bin"))
    off = find_data_attr(d)
    assert off is not None, "No $DATA attribute (type 0x80) found in repaired entry"
    assert d[off + 8] == 1, "$DATA attribute must be non-resident"
    mp_off = struct.unpack_from('<H', d, off + 0x20)[0]
    runs = decode_mapping_pairs(d, off + mp_off)
    assert len(runs) == 3, f"Expected 3 runs in runlist, got {len(runs)}: {runs}"


def test_repaired_mft_runlist_values():
    d = read_file(os.path.join(OUTPUT_DIR, "repaired_mft_entry.bin"))
    off = find_data_attr(d)
    assert off is not None
    mp_off = struct.unpack_from('<H', d, off + 0x20)[0]
    runs = decode_mapping_pairs(d, off + mp_off)
    for i, ((exp_len, exp_lcn), (got_len, got_lcn)) in enumerate(
            zip(EXPECTED_RUNLIST, runs)):
        assert got_len == exp_len, \
            f"Run {i}: length 0x{got_len:x} != expected 0x{exp_len:x}"
        assert got_lcn == exp_lcn, \
            f"Run {i}: LCN 0x{got_lcn:x} != expected 0x{exp_lcn:x}"


def test_repaired_mft_highest_vcn():
    d = read_file(os.path.join(OUTPUT_DIR, "repaired_mft_entry.bin"))
    off = find_data_attr(d)
    assert off is not None
    hv = struct.unpack_from('<Q', d, off + 0x18)[0]
    assert hv == EXPECTED_HIGHEST_VCN, \
        f"highest_vcn 0x{hv:x} != expected 0x{EXPECTED_HIGHEST_VCN:x}"


def test_repaired_mft_total_clusters():
    d = read_file(os.path.join(OUTPUT_DIR, "repaired_mft_entry.bin"))
    off = find_data_attr(d)
    assert off is not None
    mp_off = struct.unpack_from('<H', d, off + 0x20)[0]
    runs = decode_mapping_pairs(d, off + mp_off)
    total = sum(length for length, _ in runs)
    assert total == EXPECTED_TOTAL_CLUSTERS, \
        f"Total clusters 0x{total:x} != expected 0x{EXPECTED_TOTAL_CLUSTERS:x}"


# ==================== Boot sector tests ====================

def test_boot_sector_exists():
    p = os.path.join(OUTPUT_DIR, "repaired_boot_sector.bin")
    assert os.path.isfile(p), f"Missing {p}"
    d = read_file(p)
    assert len(d) == 512, f"Boot sector must be 512 bytes, got {len(d)}"


def test_boot_sector_ntfs_signature():
    d = read_file(os.path.join(OUTPUT_DIR, "repaired_boot_sector.bin"))
    assert d[3:7] == b'NTFS', "Boot sector must contain 'NTFS' OEM ID"


def test_boot_sector_volume_size():
    d = read_file(os.path.join(OUTPUT_DIR, "repaired_boot_sector.bin"))
    ts = struct.unpack_from('<Q', d, 0x28)[0]
    assert ts == EXPECTED_TOTAL_SECTORS, \
        f"Total sectors {ts} != expected {EXPECTED_TOTAL_SECTORS}"


# ==================== Forensic report tests ====================

def test_forensic_report_exists():
    p = os.path.join(OUTPUT_DIR, "forensic_report.json")
    assert os.path.isfile(p), f"Missing {p}"
    with open(p) as f:
        d = json.load(f)
    assert isinstance(d, dict), "forensic_report.json must contain a JSON object"


def test_forensic_report_selected_offset():
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    assert "selected_record_offset" in d, "Missing 'selected_record_offset' key"
    val = _parse_offset(d["selected_record_offset"])
    assert val == CORRECT_RECORD_OFFSET, \
        f"Selected offset {val} (0x{val:x}) != expected 0x{CORRECT_RECORD_OFFSET:x}"


def test_forensic_report_candidates_present():
    """All MFT records in the capture must be evaluated."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    assert "candidate_records" in d, "Missing 'candidate_records' key"
    candidates = d["candidate_records"]
    assert len(candidates) >= 6, \
        f"Expected at least 6 candidate evaluations, got {len(candidates)}"
    for c in candidates:
        assert "offset" in c, "Each candidate must have 'offset'"
        assert "verdict" in c, "Each candidate must have 'verdict'"
        assert "reason" in c, "Each candidate must have 'reason'"
        assert c["verdict"] in ("accepted", "rejected"), \
            f"Verdict must be 'accepted' or 'rejected', got '{c['verdict']}'"


def test_forensic_report_deceptive_rejected():
    """Record at 0x4000 has overlapping extents and must be rejected."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    candidates = d["candidate_records"]
    deceptive = [c for c in candidates
                 if _parse_offset(c["offset"]) == DECEPTIVE_RECORD_OFFSET]
    assert len(deceptive) >= 1, \
        f"No candidate evaluation found for deceptive record at 0x{DECEPTIVE_RECORD_OFFSET:x}"
    assert deceptive[0]["verdict"] == "rejected", \
        f"Deceptive record at 0x{DECEPTIVE_RECORD_OFFSET:x} must be rejected"


def test_forensic_report_correct_accepted():
    """Record at 0x7000 must be accepted as the repair source."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    candidates = d["candidate_records"]
    correct = [c for c in candidates
               if _parse_offset(c["offset"]) == CORRECT_RECORD_OFFSET]
    assert len(correct) >= 1, \
        f"No candidate evaluation found for correct record at 0x{CORRECT_RECORD_OFFSET:x}"
    assert correct[0]["verdict"] == "accepted", \
        f"Correct record at 0x{CORRECT_RECORD_OFFSET:x} must be accepted"


def test_forensic_report_exactly_one_accepted():
    """Exactly one candidate should be accepted."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    candidates = d["candidate_records"]
    accepted = [c for c in candidates if c["verdict"] == "accepted"]
    assert len(accepted) == 1, \
        f"Expected exactly 1 accepted candidate, got {len(accepted)}"


def test_forensic_report_correct_runlist():
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    assert "correct_runlist" in d, "Missing 'correct_runlist' key"
    rl = d["correct_runlist"]
    assert len(rl) == 3, f"Expected 3 runs in correct_runlist, got {len(rl)}"
    for i, (entry, (exp_len, exp_lcn)) in enumerate(zip(rl, EXPECTED_RUNLIST)):
        assert entry["lcn"] == exp_lcn, \
            f"Run {i}: lcn {entry['lcn']} != {exp_lcn}"
        assert entry["length"] == exp_len, \
            f"Run {i}: length {entry['length']} != {exp_len}"


def test_forensic_report_highest_vcn():
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    assert "repaired_highest_vcn" in d, "Missing 'repaired_highest_vcn' key"
    assert d["repaired_highest_vcn"] == EXPECTED_HIGHEST_VCN, \
        f"repaired_highest_vcn {d['repaired_highest_vcn']} != {EXPECTED_HIGHEST_VCN}"


def test_forensic_report_volume_sectors():
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    assert "original_volume_sectors" in d, "Missing 'original_volume_sectors' key"
    assert d["original_volume_sectors"] == EXPECTED_TOTAL_SECTORS, \
        f"original_volume_sectors {d['original_volume_sectors']} != {EXPECTED_TOTAL_SECTORS}"


# ==================== Quasi-valid candidate test ====================

def test_quasi_valid_rejected():
    """Record at 0x9000 passes standard checks but must be rejected via
    deeper cross-validation (e.g. boot sector MFT location mismatch)."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    candidates = d["candidate_records"]
    quasi = [c for c in candidates
             if _parse_offset(c["offset"]) == QUASI_VALID_OFFSET]
    assert len(quasi) >= 1, \
        f"No candidate evaluation found for quasi-valid record at 0x{QUASI_VALID_OFFSET:x}"
    assert quasi[0]["verdict"] == "rejected", \
        (f"Quasi-valid record at 0x{QUASI_VALID_OFFSET:x} must be rejected — "
         "it passes standard structural checks but is inconsistent with volume metadata")
    assert len(quasi[0]["reason"]) >= 20, \
        "Rejection reason for quasi-valid candidate must be substantive"


# ==================== Methodology design tests ====================

def test_validation_methodology_exists():
    """Solver must design at least 4 validation criteria."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    assert "validation_methodology" in d, "Missing 'validation_methodology' key"
    methodology = d["validation_methodology"]
    assert isinstance(methodology, list), "validation_methodology must be an array"
    assert len(methodology) >= 4, \
        f"Expected at least 4 validation criteria, got {len(methodology)}"


def test_validation_methodology_structure():
    """Each criterion must have name, description, and rationale."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    for i, criterion in enumerate(d["validation_methodology"]):
        assert "criterion" in criterion, \
            f"Criterion {i} missing 'criterion' field"
        assert "description" in criterion, \
            f"Criterion {i} missing 'description' field"
        assert "rationale" in criterion, \
            f"Criterion {i} missing 'rationale' field"
        assert isinstance(criterion["criterion"], str) and len(criterion["criterion"]) > 0, \
            f"Criterion {i} has empty or non-string 'criterion' name"
        assert isinstance(criterion["description"], str) and len(criterion["description"]) >= 15, \
            f"Criterion {i} description too brief (must be >= 15 characters)"
        assert isinstance(criterion["rationale"], str) and len(criterion["rationale"]) >= 15, \
            f"Criterion {i} rationale too brief (must be >= 15 characters)"


def test_confidence_assessment():
    """Solver must assess confidence in their recovery."""
    with open(os.path.join(OUTPUT_DIR, "forensic_report.json")) as f:
        d = json.load(f)
    assert "confidence_assessment" in d, "Missing 'confidence_assessment' key"
    ca = d["confidence_assessment"]
    assert isinstance(ca, dict), "confidence_assessment must be an object"
    assert "level" in ca, "Missing 'level' in confidence_assessment"
    assert ca["level"] in ("high", "medium", "low"), \
        f"Confidence level must be 'high', 'medium', or 'low', got '{ca['level']}'"
    assert "justification" in ca, "Missing 'justification' in confidence_assessment"
    assert isinstance(ca["justification"], str) and len(ca["justification"]) >= 20, \
        "Confidence justification must be substantive (>= 20 characters)"

"""
Tests for forensic ZIP archive recovery and multi-tool analysis pipeline.
Verifies extraction, raw binary parsing, binwalk scanning, YARA classification,
ssdeep fuzzy hashing, and consolidated report generation.
"""

import json
import os
import re
import subprocess
import hashlib
import sqlite3
import zlib

TOOL = "/app/zipforensics.py"
EXTRACTED = "/app/extracted"
REPORT = "/app/report.json"
INTEGRITY = "/app/integrity.sha256"
EVIDENCE = "/app/evidence.bin"
DB = "/app/casedb.sqlite"
BINWALK_SCAN = "/app/binwalk_scan.json"
YARA_RULES = "/app/classify.yar"
YARA_RESULTS = "/app/yara_results.json"
SSDEEP_FILE = "/app/integrity.ssdeep"


def get_expected_hashes():
    """Get expected SHA-256 hashes from the case database."""
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT specimen_id, sha256 FROM specimens ORDER BY specimen_id"
    ).fetchall()
    conn.close()
    return {sid: sha for sid, sha in rows}


def get_case_refs():
    """Get case references from the database."""
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT specimen_id, case_ref FROM specimens ORDER BY specimen_id"
    ).fetchall()
    conn.close()
    return {sid: ref for sid, ref in rows}


def run_tool(filepath):
    """Run the forensic analyzer on a file and return parsed JSON."""
    result = subprocess.run(
        ["python3", TOOL, filepath],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Tool failed on {filepath}:\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return json.loads(result.stdout)


# ---- Extraction tests ----

def test_extracted_directory_exists():
    assert os.path.isdir(EXTRACTED), "/app/extracted/ directory not found"


def test_extracted_count():
    expected = get_expected_hashes()
    files = [f for f in os.listdir(EXTRACTED) if f.endswith(".zip")]
    assert len(files) == len(expected), (
        f"Expected {len(expected)} specimens, found {len(files)}"
    )


def test_extracted_hashes():
    """Verify extracted specimens match SHA-256 hashes in the case database."""
    expected = get_expected_hashes()
    for sid, expected_hash in expected.items():
        path = os.path.join(EXTRACTED, f"specimen_{sid}.zip")
        assert os.path.isfile(path), f"Missing {path}"
        with open(path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        assert actual_hash == expected_hash, (
            f"specimen_{sid}.zip hash mismatch: "
            f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
        )


# ---- Integrity manifest tests ----

def test_integrity_manifest_exists():
    assert os.path.isfile(INTEGRITY), "integrity.sha256 not found"


def test_integrity_manifest_content():
    expected = get_expected_hashes()
    with open(INTEGRITY) as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == len(expected), (
        f"Expected {len(expected)} lines in integrity manifest, got {len(lines)}"
    )
    for line in lines:
        parts = line.split("  ", 1)
        assert len(parts) == 2, f"Invalid sha256sum format: {line}"
        sha, filename = parts
        assert len(sha) == 64, f"Invalid SHA-256 length: {sha}"


# ---- Parser structural tests ----

def test_parser_exists():
    assert os.path.isfile(TOOL), "zipforensics.py not found at /app/"


def test_no_zipfile_import():
    """The parser must not use Python's built-in zipfile module."""
    with open(TOOL, "r") as f:
        source = f.read()
    assert "import zipfile" not in source, "Must not use zipfile module"
    assert "from zipfile" not in source, "Must not use zipfile module"


# ---- Parser correctness: specimen 1 (basic stored archive) ----

def test_stored_basic():
    r = run_tool(os.path.join(EXTRACTED, "specimen_1.zip"))
    assert r["total_entries"] == 1
    assert r["is_zip64"] is False
    assert r["prepended_data_size"] == 0
    e = r["entries"][0]
    assert e["filename"] == "hello.txt"
    assert e["compression_method"] == 0
    assert e["uncompressed_size"] == 13


def test_stored_timestamp():
    r = run_tool(os.path.join(EXTRACTED, "specimen_1.zip"))
    e = r["entries"][0]
    assert e["mod_datetime"] == "2024-12-25T14:30:00"


def test_stored_crc32():
    r = run_tool(os.path.join(EXTRACTED, "specimen_1.zip"))
    e = r["entries"][0]
    expected_crc = f"{zlib.crc32(b'Hello, World!') & 0xFFFFFFFF:08x}"
    assert e["crc32"] == expected_crc


# ---- Parser correctness: specimen 2 (non-ASCII filename encoding) ----

def test_sjis_filename():
    r = run_tool(os.path.join(EXTRACTED, "specimen_2.zip"))
    assert r["total_entries"] == 1
    e = r["entries"][0]
    assert "\u30c6\u30b9\u30c8" in e["filename"], (
        f"Expected katakana in filename, got: {e['filename']}"
    )
    assert e["filename_encoding"] == "shift_jis"


def test_sjis_metadata():
    r = run_tool(os.path.join(EXTRACTED, "specimen_2.zip"))
    e = r["entries"][0]
    assert e["uncompressed_size"] == 12
    assert e["mod_datetime"] == "2023-06-15T10:15:00"


# ---- Parser correctness: specimen 3 (ambiguous end-of-archive marker) ----

def test_fake_eocd_handling():
    """Parser must correctly identify the real end-of-archive record."""
    r = run_tool(os.path.join(EXTRACTED, "specimen_3.zip"))
    assert r["total_entries"] == 1, (
        "Parser reported wrong entry count (likely confused by structural ambiguity)"
    )
    e = r["entries"][0]
    assert e["filename"] == "readme.txt"


def test_fake_eocd_content():
    r = run_tool(os.path.join(EXTRACTED, "specimen_3.zip"))
    e = r["entries"][0]
    assert e["uncompressed_size"] == 56


# ---- Parser correctness: specimen 4 (offset adjustment required) ----

def test_prepended_detection():
    r = run_tool(os.path.join(EXTRACTED, "specimen_4.zip"))
    assert r["prepended_data_size"] == 4096
    assert r["total_entries"] == 1


def test_prepended_offsets():
    r = run_tool(os.path.join(EXTRACTED, "specimen_4.zip"))
    e = r["entries"][0]
    assert e["filename"] == "payload.txt"
    assert e["uncompressed_size"] == 10
    assert e["local_header_offset"] == 4096


# ---- Parser correctness: specimen 5 (extended format) ----

def test_zip64_detected():
    r = run_tool(os.path.join(EXTRACTED, "specimen_5.zip"))
    assert r["is_zip64"] is True
    assert r["total_entries"] == 1


def test_zip64_entry():
    r = run_tool(os.path.join(EXTRACTED, "specimen_5.zip"))
    e = r["entries"][0]
    assert e["filename"] == "data.txt"
    assert e["uncompressed_size"] == 18


# ---- Binwalk scan tests ----

def test_binwalk_scan_exists():
    assert os.path.isfile(BINWALK_SCAN), "binwalk_scan.json not found"


def test_binwalk_scan_structure():
    with open(BINWALK_SCAN) as f:
        scan = json.load(f)
    assert "signatures" in scan, "Missing 'signatures' key"
    assert "total_signatures" in scan, "Missing 'total_signatures' key"
    assert isinstance(scan["signatures"], list)
    assert scan["total_signatures"] == len(scan["signatures"])
    for sig in scan["signatures"]:
        assert "offset" in sig, "Signature missing 'offset'"
        assert "description" in sig, "Signature missing 'description'"
        assert isinstance(sig["offset"], int)
        assert isinstance(sig["description"], str)


def test_binwalk_scan_zip_offsets():
    """Verify binwalk found ZIP signatures at valid PK offsets in evidence.bin."""
    with open(BINWALK_SCAN) as f:
        scan = json.load(f)
    with open(EVIDENCE, "rb") as f:
        evidence = f.read()
    zip_sigs = [s for s in scan["signatures"]
                if "zip" in s["description"].lower()]
    assert len(zip_sigs) >= 5, (
        f"Expected at least 5 ZIP-related signatures, found {len(zip_sigs)}"
    )
    for sig in zip_sigs:
        offset = sig["offset"]
        assert 0 <= offset < len(evidence), f"Offset {offset} out of range"
        assert evidence[offset:offset + 2] == b'PK', (
            f"No PK signature at reported offset {offset}"
        )


# ---- YARA classification tests ----

def test_yara_rules_exist():
    assert os.path.isfile(YARA_RULES), "classify.yar not found"


def test_yara_rules_have_metadata():
    """Each rule must have author, description, and severity metadata."""
    with open(YARA_RULES) as f:
        content = f.read()
    rules = re.findall(r'\brule\s+\w+', content)
    assert len(rules) >= 4, (
        f"Expected at least 4 YARA rules, found {len(rules)}"
    )
    assert content.count("author") >= 4, "Not all rules have 'author' metadata"
    assert content.count("description") >= 4, "Not all rules have 'description' metadata"
    assert content.count("severity") >= 4, "Not all rules have 'severity' metadata"


def test_yara_results_json_exists():
    assert os.path.isfile(YARA_RESULTS), "yara_results.json not found"


def test_yara_results_consistency():
    """Running yara independently must produce results matching yara_results.json."""
    with open(YARA_RESULTS) as f:
        results = json.load(f)
    for filename, expected_matches in results.items():
        specimen_path = os.path.join(EXTRACTED, filename)
        assert os.path.exists(specimen_path), f"Missing {specimen_path}"
        proc = subprocess.run(
            ["yara", YARA_RULES, specimen_path],
            capture_output=True, text=True, timeout=15,
        )
        actual_matches = []
        for line in proc.stdout.strip().split('\n'):
            line = line.strip()
            if line:
                rule_name = line.split()[0]
                actual_matches.append(rule_name)
        assert sorted(actual_matches) == sorted(expected_matches), (
            f"{filename}: independent yara run gave {actual_matches}, "
            f"reported {expected_matches}"
        )


def test_yara_detects_zip64():
    """specimen_5 (zip64) must match at least one YARA rule."""
    proc = subprocess.run(
        ["yara", YARA_RULES, os.path.join(EXTRACTED, "specimen_5.zip")],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.stdout.strip(), "No YARA matches for specimen_5 (zip64 archive)"


def test_yara_detects_prepended():
    """specimen_4 (prepended ELF data) must match at least one YARA rule."""
    proc = subprocess.run(
        ["yara", YARA_RULES, os.path.join(EXTRACTED, "specimen_4.zip")],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.stdout.strip(), "No YARA matches for specimen_4 (prepended data)"


def test_yara_detects_sjis():
    """specimen_2 (Shift-JIS filenames) must match at least one YARA rule."""
    proc = subprocess.run(
        ["yara", YARA_RULES, os.path.join(EXTRACTED, "specimen_2.zip")],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.stdout.strip(), "No YARA matches for specimen_2 (SJIS encoding)"


def test_yara_detects_ambiguous_eocd():
    """specimen_3 (multiple EOCD signatures) must match at least one YARA rule."""
    proc = subprocess.run(
        ["yara", YARA_RULES, os.path.join(EXTRACTED, "specimen_3.zip")],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.stdout.strip(), "No YARA matches for specimen_3 (ambiguous EOCD)"


def test_yara_basic_fewer_matches():
    """Basic stored archive must match strictly fewer rules than specialized specimens."""
    proc1 = subprocess.run(
        ["yara", YARA_RULES, os.path.join(EXTRACTED, "specimen_1.zip")],
        capture_output=True, text=True, timeout=15,
    )
    proc5 = subprocess.run(
        ["yara", YARA_RULES, os.path.join(EXTRACTED, "specimen_5.zip")],
        capture_output=True, text=True, timeout=15,
    )
    matches_1 = len([l for l in proc1.stdout.strip().split('\n') if l.strip()])
    matches_5 = len([l for l in proc5.stdout.strip().split('\n') if l.strip()])
    assert matches_1 < matches_5, (
        f"Basic specimen matched {matches_1} rules, zip64 matched {matches_5} — "
        "YARA rules are not discriminating between structural classes"
    )


# ---- ssdeep fuzzy hash tests ----

def test_ssdeep_file_exists():
    assert os.path.isfile(SSDEEP_FILE), "integrity.ssdeep not found"


def test_ssdeep_format():
    """Verify ssdeep output file has correct format with entries for all specimens."""
    with open(SSDEEP_FILE) as f:
        content = f.read().strip()
    lines = content.split('\n')
    data_lines = [l for l in lines if l.strip() and not l.startswith('ssdeep,')]
    expected = get_expected_hashes()
    assert len(data_lines) == len(expected), (
        f"Expected {len(expected)} ssdeep entries, found {len(data_lines)}"
    )
    for line in data_lines:
        assert ',' in line, f"Invalid ssdeep format (no comma): {line}"
        hash_part = line.rsplit(',', 1)[0]
        assert ':' in hash_part, f"Invalid ssdeep hash format (no colon): {hash_part}"


def test_ssdeep_report_consistency():
    """Verify reported ssdeep hashes match actual ssdeep tool output."""
    with open(REPORT) as f:
        report = json.load(f)
    for spec in report["specimens"]:
        sid = spec["specimen_id"]
        specimen_path = os.path.join(EXTRACTED, f"specimen_{sid}.zip")
        proc = subprocess.run(
            ["ssdeep", specimen_path],
            capture_output=True, text=True, timeout=15,
        )
        lines = [l.strip() for l in proc.stdout.strip().split('\n')
                 if l.strip() and not l.startswith('ssdeep,')]
        assert len(lines) >= 1, f"ssdeep produced no output for specimen_{sid}"
        actual_hash = lines[0].rsplit(',', 1)[0]
        assert actual_hash == spec["ssdeep"], (
            f"specimen_{sid}: ssdeep mismatch: "
            f"tool={actual_hash}, reported={spec['ssdeep']}"
        )


# ---- Report tests ----

def test_report_exists():
    assert os.path.isfile(REPORT), "/app/report.json not found"


def test_report_structure():
    with open(REPORT) as f:
        report = json.load(f)
    assert "case_id" in report
    assert "analyst" in report
    assert "specimens" in report
    assert isinstance(report["specimens"], list)
    assert len(report["specimens"]) == 5


def test_report_case_metadata():
    with open(REPORT) as f:
        report = json.load(f)
    conn = sqlite3.connect(DB)
    case = conn.execute("SELECT case_id, analyst FROM case_info").fetchone()
    conn.close()
    assert report["case_id"] == case[0]
    assert report["analyst"] == case[1]


def test_report_specimen_fields():
    with open(REPORT) as f:
        report = json.load(f)
    for spec in report["specimens"]:
        assert "specimen_id" in spec
        assert "sha256" in spec
        assert "ssdeep" in spec
        assert "case_ref" in spec
        assert "extraction_offset" in spec
        assert "extraction_size" in spec
        assert "yara_matches" in spec
        assert "analysis" in spec
        assert isinstance(spec["analysis"], dict)
        assert isinstance(spec["yara_matches"], list)
        assert isinstance(spec["ssdeep"], str)
        assert ':' in spec["ssdeep"], (
            f"Specimen {spec['specimen_id']}: ssdeep value missing colon separator"
        )


def test_report_extraction_offsets():
    """Verify reported offsets actually locate the archives in evidence.bin."""
    with open(EVIDENCE, "rb") as f:
        evidence = f.read()
    with open(REPORT) as f:
        report = json.load(f)
    for spec in report["specimens"]:
        offset = spec["extraction_offset"]
        size = spec["extraction_size"]
        chunk = evidence[offset:offset + size]
        actual_hash = hashlib.sha256(chunk).hexdigest()
        assert actual_hash == spec["sha256"], (
            f"Specimen {spec['specimen_id']}: "
            f"evidence.bin[{offset}:{offset + size}] hash does not match reported sha256"
        )


def test_report_case_references():
    """Verify case references match the database."""
    with open(REPORT) as f:
        report = json.load(f)
    expected = get_case_refs()
    for spec in report["specimens"]:
        sid = spec["specimen_id"]
        assert spec["case_ref"] == expected[sid], (
            f"Specimen {sid}: case_ref mismatch"
        )


import hashlib
import json
import os
import subprocess

# SHA-256 of the correct answer (double-hashed to prevent trivial extraction)
# The agent must actually extract the payload; reversing this hash is infeasible.
EXPECTED_DOUBLE_HASH = "960ede130a18f81cd1bdf9557a742eb839a57261b7c36f72f8713bb0702ac979"
EXPECTED_PAYLOAD_SIZE = 4096

# Forensic report expected classifications
EXPECTED_ENTRY_POINT = "m4/build-to-host.m4"
EXPECTED_BACKDOOR_FILES = {
    "m4/build-to-host.m4",
    "tests/files/bad-stream.xz",
    "tests/files/good-archive.lzma",
}
KNOWN_BENIGN_SUSPICIOUS = {
    "scripts/gen-corpus.sh",
    "tests/fixtures/entropy_test.dat",
    "m4/ax_check_compile_flag.m4",
}


def _normalize_path(p):
    """Strip common prefixes to get path relative to project root."""
    p = p.strip()
    for prefix in ["/app/project/", "./", "/"]:
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p.rstrip("/")


# ===== PAYLOAD EXTRACTION TESTS =====

def test_answer_file_exists():
    """answer.txt must exist at /app/answer.txt."""
    assert os.path.exists("/app/answer.txt"), \
        "answer.txt not found at /app/answer.txt"


def test_answer_format():
    """answer.txt must contain a 64-character lowercase hex string."""
    with open("/app/answer.txt") as f:
        answer = f.read().strip()
    assert len(answer) == 64, \
        f"Expected 64-char hex string, got {len(answer)} chars"
    assert all(c in "0123456789abcdef" for c in answer), \
        "Answer must be lowercase hex"


def test_answer_correct():
    """The SHA-256 of the answer must match the expected double-hash."""
    with open("/app/answer.txt") as f:
        answer = f.read().strip()
    computed = hashlib.sha256(answer.encode()).hexdigest()
    assert computed == EXPECTED_DOUBLE_HASH, \
        "Incorrect payload hash"


def test_payload_file_exists():
    """payload.bin must exist at /app/payload.bin."""
    assert os.path.exists("/app/payload.bin"), \
        "payload.bin not found at /app/payload.bin"


def test_payload_size():
    """payload.bin must be exactly the expected size."""
    with open("/app/payload.bin", "rb") as f:
        payload = f.read()
    assert len(payload) == EXPECTED_PAYLOAD_SIZE, \
        f"Expected {EXPECTED_PAYLOAD_SIZE} bytes, got {len(payload)}"


def test_payload_matches_answer():
    """The SHA-256 of payload.bin must match the answer in answer.txt."""
    with open("/app/payload.bin", "rb") as f:
        payload = f.read()
    with open("/app/answer.txt") as f:
        answer = f.read().strip()
    assert hashlib.sha256(payload).hexdigest() == answer, \
        "payload.bin SHA-256 does not match answer.txt"


# ===== FORENSIC REPORT TESTS =====

def test_report_exists():
    """report.json must exist at /app/report.json."""
    assert os.path.exists("/app/report.json"), \
        "report.json not found at /app/report.json"


def test_report_structure():
    """report.json must have the required top-level keys."""
    with open("/app/report.json") as f:
        report = json.load(f)
    assert "backdoor_entry_point" in report, \
        "Missing key: backdoor_entry_point"
    assert "backdoor_files" in report, \
        "Missing key: backdoor_files"
    assert "benign_suspicious_files" in report, \
        "Missing key: benign_suspicious_files"
    assert isinstance(report["backdoor_files"], list), \
        "backdoor_files must be a list"
    assert isinstance(report["benign_suspicious_files"], list), \
        "benign_suspicious_files must be a list"


def test_entry_point_correct():
    """The backdoor entry point must be correctly identified."""
    with open("/app/report.json") as f:
        report = json.load(f)
    entry = _normalize_path(report["backdoor_entry_point"])
    assert entry == EXPECTED_ENTRY_POINT, \
        f"Wrong entry point: got '{entry}', expected '{EXPECTED_ENTRY_POINT}'"


def test_all_backdoor_files_identified():
    """All actual backdoor files must appear in backdoor_files."""
    with open("/app/report.json") as f:
        report = json.load(f)
    reported = {_normalize_path(p) for p in report["backdoor_files"]}
    for expected in EXPECTED_BACKDOOR_FILES:
        assert expected in reported, \
            f"Missing backdoor file in report: {expected}"


def test_no_false_positives_in_backdoor():
    """Benign files must not appear in backdoor_files."""
    with open("/app/report.json") as f:
        report = json.load(f)
    reported_backdoor = {_normalize_path(p) for p in report["backdoor_files"]}
    for benign in KNOWN_BENIGN_SUSPICIOUS:
        assert benign not in reported_backdoor, \
            f"False positive: '{benign}' is benign but listed as backdoor"


def test_no_false_negatives_in_benign():
    """Backdoor files must not appear in benign_suspicious_files."""
    with open("/app/report.json") as f:
        report = json.load(f)
    reported_benign = {_normalize_path(p) for p in report["benign_suspicious_files"]}
    for mal in EXPECTED_BACKDOOR_FILES:
        assert mal not in reported_benign, \
            f"False negative: '{mal}' is malicious but listed as benign"


def test_benign_suspicious_files_classified():
    """All known benign-but-suspicious files must be correctly classified."""
    with open("/app/report.json") as f:
        report = json.load(f)
    reported_benign = {_normalize_path(p) for p in report["benign_suspicious_files"]}
    for expected in KNOWN_BENIGN_SUSPICIOUS:
        assert expected in reported_benign, \
            f"Missing benign-suspicious classification: {expected}"


# ===== DETECTION SCRIPT TESTS =====

def test_detect_script_exists():
    """detect.py must exist at /app/detect.py."""
    assert os.path.exists("/app/detect.py"), \
        "detect.py not found at /app/detect.py"


def test_detect_script_runs():
    """detect.py must execute successfully against /app/project/."""
    result = subprocess.run(
        ["python3", "/app/detect.py", "/app/project/"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, \
        f"detect.py exited with code {result.returncode}: {result.stderr}"


def test_detect_output_valid_json():
    """detect.py output must be valid JSON with correct structure."""
    result = subprocess.run(
        ["python3", "/app/detect.py", "/app/project/"],
        capture_output=True, text=True, timeout=60
    )
    data = json.loads(result.stdout)
    assert "alerts" in data, "Output must contain 'alerts' key"
    assert isinstance(data["alerts"], list), "'alerts' must be a list"
    for alert in data["alerts"]:
        assert "file" in alert, "Each alert must have 'file'"
        assert "risk" in alert, "Each alert must have 'risk'"
        assert "indicator" in alert, "Each alert must have 'indicator'"
        assert alert["risk"] in ("high", "medium", "low"), \
            f"Risk must be high/medium/low, got '{alert['risk']}'"
        assert len(alert["indicator"]) > 0, "Indicator must be non-empty"


def test_detect_flags_all_backdoor_files_high():
    """All backdoor files must be flagged as high risk by the detector."""
    result = subprocess.run(
        ["python3", "/app/detect.py", "/app/project/"],
        capture_output=True, text=True, timeout=60
    )
    data = json.loads(result.stdout)
    high_risk_files = {_normalize_path(a["file"]) for a in data["alerts"]
                       if a["risk"] == "high"}
    for bf in EXPECTED_BACKDOOR_FILES:
        assert bf in high_risk_files, \
            f"Backdoor file '{bf}' not flagged as high risk by detector"


def test_detect_no_benign_false_positives_high():
    """Benign-but-suspicious files must not be flagged as high risk."""
    result = subprocess.run(
        ["python3", "/app/detect.py", "/app/project/"],
        capture_output=True, text=True, timeout=60
    )
    data = json.loads(result.stdout)
    high_risk_files = {_normalize_path(a["file"]) for a in data["alerts"]
                       if a["risk"] == "high"}
    for benign in KNOWN_BENIGN_SUSPICIOUS:
        assert benign not in high_risk_files, \
            f"Benign file '{benign}' incorrectly flagged as high risk"

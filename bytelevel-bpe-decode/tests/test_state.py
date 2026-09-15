"""Tests for ByteLevel BPE tokenizer decode pipeline and vulnerability auditor."""

import json
import os
import subprocess

import pytest

# ── Expected decode outputs ──
EXPECTED = {
    "seq_basic":            "hello",
    "seq_bpe":              "hello world",
    "seq_space_bpe":        " the message",
    "seq_added_czech":      "Začnimo",
    "seq_added_serbian":    "kuća",
    "seq_added_croatian":   "međa",
    "seq_mixed":            "hello Začnimo the message",
    "seq_multi_added":      "Začnimo kuća međa",
    "seq_newline":          "hello\nworld",
    "seq_special":          "hello world",
    "seq_munchen":          "München",
    "seq_lodz":             "Łódź",
    "seq_cross_utf8":       "hüt",
    "seq_sentence":         "hello world is Začnimo",
    "seq_naive":            "naïve",
    "seq_european_cities":  "Łódź München Začnimo kuća",
    "seq_cafe":             "café",
    "seq_mixed_norm":       "Začnimo café",
}

# ── Expected audit results ──
HAZARDOUS_TOKEN_IDS = {300, 301, 302, 303, 305, 306, 307}
SAFE_TOKEN_IDS = {304}

EXPECTED_HAZARDOUS_CHARS = {
    300: ["č"],
    301: ["ć"],
    302: ["đ"],
    303: ["ü"],
    305: ["Ł", "ó"],
    306: ["ï"],
    307: ["é"],
}

EXPECTED_RISK = {
    300: "low",
    301: "low",
    302: "low",
    303: "low",
    305: "low",
    306: "low",
    307: "high",
}


@pytest.fixture(scope="session")
def decoded_output():
    """Run decode.py and load the output."""
    result = subprocess.run(
        ["python3", "/app/decode.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"decode.py failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    output_path = "/app/decoded_output.json"
    assert os.path.exists(output_path), "decoded_output.json was not created"

    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "results" in data, "Output JSON missing 'results' key"
    return data["results"]


@pytest.fixture(scope="session")
def audit_report():
    """Run audit.py and load the report."""
    result = subprocess.run(
        ["python3", "/app/audit.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"audit.py failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    report_path = "/app/audit_report.json"
    assert os.path.exists(report_path), "audit_report.json was not created"

    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════
# Decode tests
# ═══════════════════════════════════════════════════════════════

def test_decode_py_exists():
    """The agent must create /app/decode.py."""
    assert os.path.exists("/app/decode.py"), "decode.py not found at /app/decode.py"


def test_all_sequences_present(decoded_output):
    """Every expected sequence ID must appear in the output."""
    for seq_id in EXPECTED:
        assert seq_id in decoded_output, f"Missing sequence '{seq_id}' in output"


@pytest.mark.parametrize("seq_id,expected_text", list(EXPECTED.items()))
def test_decode_sequence(decoded_output, seq_id, expected_text):
    """Each decoded sequence must match the expected text exactly."""
    assert seq_id in decoded_output, f"Sequence '{seq_id}' missing from output"
    actual = decoded_output[seq_id]
    assert actual == expected_text, (
        f"Sequence '{seq_id}':\n"
        f"  expected: {expected_text!r}\n"
        f"  actual:   {actual!r}"
    )


def test_no_control_chars_in_added_token_decodes(decoded_output):
    """Added-token decodes must not contain stray control characters.

    This catches the classic ByteLevel bug where characters like č (U+010D)
    get incorrectly decoded as CR (byte 0x0D).
    """
    added_token_seqs = [
        "seq_added_czech", "seq_added_serbian", "seq_added_croatian",
        "seq_munchen", "seq_lodz", "seq_naive", "seq_cafe",
    ]
    for seq_id in added_token_seqs:
        text = decoded_output[seq_id]
        for ch in text:
            code = ord(ch)
            assert code >= 32 or ch in "\n\r\t", (
                f"Control character U+{code:04X} found in '{seq_id}': {text!r}"
            )


def test_round_trip_bytes_consistency(decoded_output):
    """Verify that danger-zone characters survive the decode round-trip.

    The characters č, ć, đ, Ł, ï, é must appear literally in the output,
    not as replacement characters or byte-mangled equivalents.
    """
    checks = {
        "seq_added_czech":    "č",
        "seq_added_serbian":  "ć",
        "seq_added_croatian": "đ",
        "seq_lodz":           "Ł",
        "seq_naive":          "ï",
        "seq_cafe":           "é",
    }
    for seq_id, required_char in checks.items():
        text = decoded_output[seq_id]
        assert required_char in text, (
            f"Character {required_char!r} (U+{ord(required_char):04X}) "
            f"not found in '{seq_id}': {text!r}"
        )


def test_non_normalized_token_passthrough(decoded_output):
    """Non-normalized added tokens must be output as-is without ByteLevel decode."""
    assert decoded_output["seq_cafe"] == "café", (
        f"Non-normalized token 'café' not passed through correctly: "
        f"{decoded_output['seq_cafe']!r}"
    )


def test_mixed_normalization_modes(decoded_output):
    """Sequences mixing normalized and non-normalized tokens must decode correctly."""
    assert decoded_output["seq_mixed_norm"] == "Začnimo café", (
        f"Mixed normalization sequence incorrect: "
        f"{decoded_output['seq_mixed_norm']!r}"
    )


# ═══════════════════════════════════════════════════════════════
# Audit tests
# ═══════════════════════════════════════════════════════════════

def test_audit_py_exists():
    """The agent must create /app/audit.py."""
    assert os.path.exists("/app/audit.py"), "audit.py not found at /app/audit.py"


def test_audit_report_structure(audit_report):
    """The audit report must contain all required top-level keys."""
    assert "hazardous_tokens" in audit_report, "Missing 'hazardous_tokens' key"
    assert "safe_token_ids" in audit_report, "Missing 'safe_token_ids' key"
    assert "summary" in audit_report, "Missing 'summary' key"
    assert isinstance(audit_report["hazardous_tokens"], list)
    assert isinstance(audit_report["safe_token_ids"], list)
    assert isinstance(audit_report["summary"], str)
    assert len(audit_report["summary"]) > 0, "Summary must not be empty"


def test_audit_hazardous_token_ids(audit_report):
    """The audit must identify exactly the correct set of hazardous token IDs."""
    found_ids = {t["id"] for t in audit_report["hazardous_tokens"]}
    assert found_ids == HAZARDOUS_TOKEN_IDS, (
        f"Hazardous token IDs mismatch.\n"
        f"  expected: {sorted(HAZARDOUS_TOKEN_IDS)}\n"
        f"  actual:   {sorted(found_ids)}"
    )


def test_audit_safe_token_ids(audit_report):
    """The audit must correctly identify safe (non-hazardous) added tokens."""
    found_safe = set(audit_report["safe_token_ids"])
    assert found_safe == SAFE_TOKEN_IDS, (
        f"Safe token IDs mismatch.\n"
        f"  expected: {sorted(SAFE_TOKEN_IDS)}\n"
        f"  actual:   {sorted(found_safe)}"
    )


def test_audit_hazardous_chars(audit_report):
    """Each hazardous token must list exactly the correct hazardous characters."""
    for entry in audit_report["hazardous_tokens"]:
        tid = entry["id"]
        if tid in EXPECTED_HAZARDOUS_CHARS:
            expected_chars = EXPECTED_HAZARDOUS_CHARS[tid]
            actual_chars = entry.get("hazardous_chars", [])
            assert set(actual_chars) == set(expected_chars), (
                f"Token {tid} ({entry['content']!r}) hazardous chars mismatch.\n"
                f"  expected: {expected_chars}\n"
                f"  actual:   {actual_chars}"
            )


def test_audit_risk_levels(audit_report):
    """Risk must be 'high' for normalized=false tokens, 'low' for normalized=true."""
    for entry in audit_report["hazardous_tokens"]:
        tid = entry["id"]
        if tid in EXPECTED_RISK:
            expected_risk = EXPECTED_RISK[tid]
            actual_risk = entry.get("risk")
            assert actual_risk == expected_risk, (
                f"Token {tid} ({entry['content']!r}) risk mismatch: "
                f"expected {expected_risk!r}, got {actual_risk!r}"
            )


def test_audit_entry_structure(audit_report):
    """Each hazardous token entry must contain all required fields."""
    required_fields = {"id", "content", "hazardous_chars", "normalized", "risk"}
    for entry in audit_report["hazardous_tokens"]:
        missing = required_fields - set(entry.keys())
        assert not missing, (
            f"Hazardous token entry for ID {entry.get('id', '?')} "
            f"missing fields: {missing}"
        )


def test_audit_normalized_field_matches_config(audit_report):
    """The normalized field in the audit must match the tokenizer config."""
    expected_normalized = {
        300: True, 301: True, 302: True, 303: True,
        305: True, 306: True, 307: False,
    }
    for entry in audit_report["hazardous_tokens"]:
        tid = entry["id"]
        if tid in expected_normalized:
            assert entry["normalized"] == expected_normalized[tid], (
                f"Token {tid} normalized field mismatch: "
                f"expected {expected_normalized[tid]}, got {entry['normalized']}"
            )


# ═══════════════════════════════════════════════════════════════
# Anti-cheat: library ban
# ═══════════════════════════════════════════════════════════════

def test_no_tokenizer_library_used():
    """Verify that neither tool imports tokenizer libraries."""
    forbidden = [
        "import tokenizers", "from tokenizers",
        "import transformers", "from transformers",
    ]
    for fpath in ["/app/decode.py", "/app/audit.py"]:
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r") as f:
            content = f.read()
        for pattern in forbidden:
            assert pattern not in content, (
                f"{fpath} must not use tokenizer libraries (found '{pattern}')"
            )

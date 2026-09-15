"""Property-based verification for PII detection and format-preserving anonymization."""

import json
import os
import re
import shutil
import subprocess

import pytest

CORPUS_PATH = "/app/corpus/clinical_records.txt"
DETECTIONS_PATH = "/app/output/detections.json"
ANONYMIZED_PATH = "/app/output/anonymized.txt"

ENTITY_TYPES = [
    "CREDIT_CARD",
    "DE_HEALTH_INSURANCE",
    "DE_TAX_ID",
    "IBAN_CODE",
    "IT_FISCAL_CODE",
]
COUNT_PER_TYPE = 3
TOTAL_EXPECTED = 15

# ---------------------------------------------------------------------------
# Checksum validators (independent implementations for verification)
# ---------------------------------------------------------------------------

def _luhn_valid(s):
    digits = [int(c) for c in s if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_valid(s):
    iban = re.sub(r"\s", "", s).upper()
    if len(iban) < 15 or len(iban) > 34:
        return False
    if not iban[:2].isalpha() or not iban[2:4].isdigit():
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(
        str(ord(c) - 55) if c.isalpha() else c for c in rearranged
    )
    return int(numeric) % 97 == 1


def _iso7064_valid(s):
    if len(s) != 11 or not s.isdigit():
        return False
    p = 10
    for ch in s:
        si = (p + int(ch)) % 10
        if si == 0:
            si = 10
        p = (si * 2) % 11
    return si == 1


def _gkv_valid(s):
    if len(s) != 10 or not s[0].isalpha() or not s[1:].isdigit():
        return False
    lv = ord(s[0].upper()) - ord("A") + 1
    digits = [lv // 10, lv % 10] + [int(c) for c in s[1:]]
    mults = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = 0
    for i in range(10):
        p = digits[i] * mults[i]
        total += (p // 10 + p % 10) if p >= 10 else p
    return digits[10] == total % 10


_ODD = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15,
    "7": 17, "8": 19, "9": 21, "A": 1, "B": 0, "C": 5, "D": 7,
    "E": 9, "F": 13, "G": 15, "H": 17, "I": 19, "J": 21, "K": 2,
    "L": 4, "M": 18, "N": 20, "O": 11, "P": 3, "Q": 6, "R": 8,
    "S": 12, "T": 14, "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24,
    "Z": 23,
}
_EVEN = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9, "A": 0, "B": 1, "C": 2, "D": 3,
    "E": 4, "F": 5, "G": 6, "H": 7, "I": 8, "J": 9, "K": 10,
    "L": 11, "M": 12, "N": 13, "O": 14, "P": 15, "Q": 16, "R": 17,
    "S": 18, "T": 19, "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24,
    "Z": 25,
}


def _fiscal_code_valid(s):
    s = s.upper()
    if len(s) != 16:
        return False
    pat = re.compile(r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$")
    if not pat.match(s):
        return False
    total = 0
    for i, c in enumerate(s[:15]):
        total += _ODD[c] if (i + 1) % 2 == 1 else _EVEN[c]
    return s[15] == chr(total % 26 + ord("A"))


_VALIDATORS = {
    "CREDIT_CARD": _luhn_valid,
    "IBAN_CODE": _iban_valid,
    "DE_TAX_ID": _iso7064_valid,
    "IT_FISCAL_CODE": _fiscal_code_valid,
    "DE_HEALTH_INSURANCE": _gkv_valid,
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def corpus():
    with open(CORPUS_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="session")
def detections():
    with open(DETECTIONS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def anonymized():
    with open(ANONYMIZED_PATH, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_detections_file_exists(self):
        assert os.path.isfile(DETECTIONS_PATH), (
            f"{DETECTIONS_PATH} not found. Run the pipeline first."
        )

    def test_anonymized_file_exists(self):
        assert os.path.isfile(ANONYMIZED_PATH), (
            f"{ANONYMIZED_PATH} not found. Run the pipeline first."
        )

    def test_detections_is_valid_json_array(self):
        with open(DETECTIONS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list), "detections.json must be a JSON array"


class TestDetectionCounts:
    def test_total_detection_count(self, detections):
        assert len(detections) == TOTAL_EXPECTED, (
            f"Expected {TOTAL_EXPECTED} detections, got {len(detections)}"
        )

    @pytest.mark.parametrize("et", ENTITY_TYPES)
    def test_count_per_entity_type(self, detections, et):
        count = sum(1 for d in detections if d["entity_type"] == et)
        assert count == COUNT_PER_TYPE, (
            f"Expected {COUNT_PER_TYPE} {et}, got {count}"
        )

    def test_only_valid_entity_types(self, detections):
        found = set(d["entity_type"] for d in detections)
        assert found == set(ENTITY_TYPES), (
            f"Unexpected entity types: {found - set(ENTITY_TYPES)}"
        )


class TestDetectionRecordStructure:
    REQUIRED_KEYS = {
        "entity_type", "start", "end", "score",
        "original_value", "anonymized_value",
    }

    def test_all_required_keys_present(self, detections):
        for i, d in enumerate(detections):
            missing = self.REQUIRED_KEYS - set(d.keys())
            assert not missing, (
                f"Detection {i} missing keys: {missing}"
            )

    def test_start_end_are_integers(self, detections):
        for d in detections:
            assert isinstance(d["start"], int) and isinstance(d["end"], int)
            assert d["start"] < d["end"]


class TestDetectionChecksumValidity:
    """Every detected original_value must pass its entity type's checksum."""

    def test_all_originals_pass_checksum(self, detections):
        for d in detections:
            et = d["entity_type"]
            val = d["original_value"]
            validator = _VALIDATORS[et]
            assert validator(val), (
                f"Detected {et} original '{val}' fails checksum"
            )

    def test_detected_values_appear_in_corpus(self, detections, corpus):
        for d in detections:
            start, end = d["start"], d["end"]
            raw = corpus[start:end]
            cleaned = raw.replace("-", "").replace(" ", "")
            assert cleaned == d["original_value"], (
                f"Detection [{start}:{end}] corpus substring "
                f"'{raw}' -> '{cleaned}' != original_value '{d['original_value']}'"
            )


class TestAnonymizationChecksumValidity:
    """Every anonymized_value must pass the same checksum as its entity type."""

    def test_all_anonymized_pass_checksum(self, detections):
        for d in detections:
            et = d["entity_type"]
            anon = d["anonymized_value"]
            validator = _VALIDATORS[et]
            assert validator(anon), (
                f"Anonymized {et} value '{anon}' fails checksum"
            )


class TestAnonymizationDifference:
    """Anonymized values must differ from originals."""

    def test_all_values_differ(self, detections):
        for d in detections:
            assert d["anonymized_value"] != d["original_value"], (
                f"{d['entity_type']}: anonymized == original '{d['original_value']}'"
            )


class TestFormatPreservation:
    """Anonymized values must have the same length and structural pattern."""

    def test_length_preserved(self, detections):
        for d in detections:
            orig = d["original_value"]
            anon = d["anonymized_value"]
            assert len(anon) == len(orig), (
                f"{d['entity_type']}: length mismatch "
                f"orig={len(orig)} anon={len(anon)}"
            )

    def test_credit_card_all_digits(self, detections):
        for d in detections:
            if d["entity_type"] == "CREDIT_CARD":
                assert d["anonymized_value"].isdigit(), (
                    f"Credit card anonymized value must be all digits: "
                    f"'{d['anonymized_value']}'"
                )

    def test_iban_country_code_preserved(self, detections):
        for d in detections:
            if d["entity_type"] == "IBAN_CODE":
                orig = d["original_value"]
                anon = d["anonymized_value"]
                assert anon[:2] == orig[:2], (
                    f"IBAN country code changed: "
                    f"'{orig[:2]}' -> '{anon[:2]}'"
                )
                assert anon[2:4].isdigit(), "IBAN check digits must be numeric"

    def test_tax_id_format(self, detections):
        for d in detections:
            if d["entity_type"] == "DE_TAX_ID":
                anon = d["anonymized_value"]
                assert anon.isdigit() and len(anon) == 11, (
                    f"Tax ID must be 11 digits: '{anon}'"
                )

    def test_fiscal_code_pattern(self, detections):
        pat = re.compile(r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$")
        for d in detections:
            if d["entity_type"] == "IT_FISCAL_CODE":
                anon = d["anonymized_value"].upper()
                assert pat.match(anon), (
                    f"Fiscal code format violated: '{anon}'"
                )

    def test_gkv_format(self, detections):
        for d in detections:
            if d["entity_type"] == "DE_HEALTH_INSURANCE":
                anon = d["anonymized_value"]
                assert len(anon) == 10, f"GKV must be 10 chars: '{anon}'"
                assert anon[0].isalpha(), f"GKV must start with letter: '{anon}'"
                assert anon[1:].isdigit(), f"GKV digits 2-10 must be numeric: '{anon}'"


class TestAnonymizedText:
    """The anonymized text file must have originals removed and structure intact."""

    def test_same_total_length(self, anonymized, corpus):
        assert len(anonymized) == len(corpus), (
            f"Anonymized length {len(anonymized)} != corpus length {len(corpus)}"
        )

    def test_no_original_values_in_text(self, detections, anonymized):
        for d in detections:
            orig = d["original_value"]
            assert orig not in anonymized, (
                f"Original {d['entity_type']} value '{orig}' "
                f"still present in anonymized text"
            )

    def test_non_pii_text_preserved(self, detections, anonymized, corpus):
        spans = sorted([(d["start"], d["end"]) for d in detections])
        prev_end = 0
        for start, end in spans:
            assert anonymized[prev_end:start] == corpus[prev_end:start], (
                f"Non-PII text altered between positions {prev_end} and {start}"
            )
            prev_end = end
        if spans:
            last_end = spans[-1][1]
            assert anonymized[last_end:] == corpus[last_end:], (
                f"Non-PII text altered after position {last_end}"
            )

    def test_replacement_text_at_span_positions(self, detections, anonymized):
        """The anonymized text at each detection span must match the anonymized_value
        (possibly with formatting characters like dashes/spaces re-inserted)."""
        for d in detections:
            start, end = d["start"], d["end"]
            span_text = anonymized[start:end]
            cleaned = span_text.replace("-", "").replace(" ", "")
            assert cleaned == d["anonymized_value"], (
                f"Span [{start}:{end}] text '{span_text}' cleaned to "
                f"'{cleaned}' != anonymized_value '{d['anonymized_value']}'"
            )


class TestDeterminism:
    """Running the pipeline again with the same seed must produce identical output."""

    def test_second_run_identical(self):
        # Save first-run outputs
        shutil.copy(DETECTIONS_PATH, "/tmp/_det_first.json")
        shutil.copy(ANONYMIZED_PATH, "/tmp/_anon_first.txt")

        # Re-run the pipeline
        result = subprocess.run(
            ["python3", "/app/pipeline.py", "--seed", "42"],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Second pipeline run failed:\n{result.stderr}"
        )

        # Compare detection outputs
        with open("/tmp/_det_first.json") as f:
            first_det = f.read()
        with open(DETECTIONS_PATH) as f:
            second_det = f.read()
        assert first_det == second_det, "Detection output not deterministic"

        # Compare anonymized text
        with open("/tmp/_anon_first.txt") as f:
            first_anon = f.read()
        with open(ANONYMIZED_PATH) as f:
            second_anon = f.read()
        assert first_anon == second_anon, "Anonymized text not deterministic"

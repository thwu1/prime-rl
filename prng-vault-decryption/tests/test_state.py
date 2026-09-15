
import os
import json
import hashlib
import pytest

# SHA-256 of the correct flag
EXPECTED_FLAG_HASH = "bd5e63f2cf5fdc6cef40a1fac2db7af1100318e25c0033017754edaf8c2f093e"

# SHA-256 of the canonicalized assessment correctness signature
# Signature = "false|true|false" (patch_a|patch_b|patch_c effective values)
EXPECTED_ASSESSMENT_SIG = "0e4f164131392e323c991f6c3204a90cfc8cffbd8d1608f0cef052e0abaf6644"


# ---- Flag recovery tests ----

def test_flag_file_exists():
    """The flag file must exist at /app/flag.txt."""
    assert os.path.exists("/app/flag.txt"), \
        "Flag file /app/flag.txt does not exist"


def test_flag_not_empty():
    """The flag file must not be empty."""
    with open("/app/flag.txt", "r") as f:
        content = f.read().strip()
    assert len(content) > 0, "Flag file is empty"


def test_flag_format():
    """The flag must follow the OOO{...} format."""
    with open("/app/flag.txt", "r") as f:
        content = f.read().strip()
    assert content.startswith("OOO{"), \
        f"Flag must start with 'OOO{{', got: {content[:10]}..."
    assert content.endswith("}"), \
        f"Flag must end with '}}', got: ...{content[-10:]}"


def test_flag_hash():
    """The flag content must match the expected SHA-256 hash."""
    with open("/app/flag.txt", "r") as f:
        content = f.read().strip()
    actual_hash = hashlib.sha256(content.encode()).hexdigest()
    assert actual_hash == EXPECTED_FLAG_HASH, \
        "Flag hash mismatch: submitted flag is incorrect"


# ---- Patch assessment tests ----

def test_assessment_file_exists():
    """The assessment file must exist at /app/patch_assessment.json."""
    assert os.path.exists("/app/patch_assessment.json"), \
        "Assessment file /app/patch_assessment.json does not exist"


def test_assessment_valid_json():
    """The assessment must be valid JSON."""
    with open("/app/patch_assessment.json", "r") as f:
        data = json.load(f)
    assert isinstance(data, dict), "Assessment must be a JSON object"


def test_assessment_structure():
    """Each patch entry must have 'effective' (bool) and 'justification' (str) fields."""
    with open("/app/patch_assessment.json", "r") as f:
        data = json.load(f)
    for patch in ["patch_a", "patch_b", "patch_c"]:
        assert patch in data, f"Missing assessment for {patch}"
        assert "effective" in data[patch], \
            f"Missing 'effective' field for {patch}"
        assert isinstance(data[patch]["effective"], bool), \
            f"'effective' must be a boolean for {patch}"
        assert "justification" in data[patch], \
            f"Missing 'justification' field for {patch}"
        assert isinstance(data[patch]["justification"], str), \
            f"'justification' must be a string for {patch}"
        assert len(data[patch]["justification"]) >= 30, \
            f"Justification for {patch} must be substantive (>=30 chars)"


def test_assessment_correctness():
    """All three patch assessments must be correct."""
    with open("/app/patch_assessment.json", "r") as f:
        data = json.load(f)
    sig = "|".join(
        str(data[f"patch_{x}"]["effective"]).lower() for x in "abc"
    )
    sig_hash = hashlib.sha256(sig.encode()).hexdigest()
    assert sig_hash == EXPECTED_ASSESSMENT_SIG, \
        "One or more patch effectiveness assessments are incorrect"

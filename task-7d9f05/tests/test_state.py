
import subprocess
import tempfile
import os
import json
import re
import pytest

COMPILE_CMD = [
    "gcc", "-c", "-O0", "-fno-stack-protector", "-fno-pic",
    "-fcf-protection=none", "-std=c11",
    "-o", "/app/candidate.o", "/app/candidate.c"
]


def test_candidate_compiles():
    """Candidate.c must compile without errors."""
    result = subprocess.run(COMPILE_CMD, capture_output=True, text=True)
    assert result.returncode == 0, f"Compilation failed: {result.stderr}"


def test_no_inline_assembly():
    """Source must not contain inline assembly."""
    with open("/app/candidate.c") as f:
        source = f.read()
    for pattern in ["__asm__", "__asm", "asm("]:
        assert pattern not in source, f"Inline assembly detected: {pattern}"


def test_function_signatures_preserved():
    """Both function signatures must remain unchanged."""
    with open("/app/candidate.c") as f:
        source = f.read()
    assert "hash_entries" in source, "Function hash_entries not found"
    assert "feistel_round" in source, "Function feistel_round not found"
    assert re.search(
        r"uint32_t\s+hash_entries\s*\(\s*const\s+uint8_t\s*\*\s*data\s*,\s*uint32_t\s+size\s*\)",
        source
    ), "hash_entries signature altered"
    assert re.search(
        r"uint32_t\s+feistel_round\s*\(\s*uint32_t\s+block\s*,\s*uint32_t\s+key\s*,\s*int\s+rounds\s*\)",
        source
    ), "feistel_round signature altered"


def test_text_section_matches():
    """The .text section of candidate.o must be byte-identical to target.o."""
    result = subprocess.run(COMPILE_CMD, capture_output=True, text=True)
    assert result.returncode == 0, f"Compilation failed: {result.stderr}"

    with tempfile.TemporaryDirectory() as tmpdir:
        target_bin = os.path.join(tmpdir, "target.bin")
        candidate_bin = os.path.join(tmpdir, "candidate.bin")

        subprocess.check_call([
            "objcopy", "-O", "binary", "-j", ".text",
            "/app/target.o", target_bin
        ])
        subprocess.check_call([
            "objcopy", "-O", "binary", "-j", ".text",
            "/app/candidate.o", candidate_bin
        ])

        with open(target_bin, "rb") as f:
            target_text = f.read()
        with open(candidate_bin, "rb") as f:
            candidate_text = f.read()

    assert len(target_text) >= 64, (
        f"Target .text section unexpectedly small ({len(target_text)} bytes)"
    )

    if target_text != candidate_text:
        min_len = min(len(target_text), len(candidate_text))
        diff_count = sum(
            1 for i in range(min_len)
            if target_text[i] != candidate_text[i]
        )
        diff_count += abs(len(target_text) - len(candidate_text))

        pytest.fail(
            f".text sections do not match.\n"
            f"Target: {len(target_text)} bytes, "
            f"Candidate: {len(candidate_text)} bytes.\n"
            f"Differing bytes: {diff_count}\n"
            f"Use 'objdump -d /app/target.o' and "
            f"'objdump -d /app/candidate.o' to compare."
        )


def test_analysis_json_exists():
    """analysis.json must exist and be valid JSON with required fields."""
    assert os.path.exists("/app/analysis.json"), (
        "analysis.json not found at /app/analysis.json"
    )
    with open("/app/analysis.json") as f:
        data = json.load(f)
    assert "codegen_affecting_count" in data, "Missing codegen_affecting_count"
    assert "cosmetic_count" in data, "Missing cosmetic_count"
    assert isinstance(data["codegen_affecting_count"], int)
    assert isinstance(data["cosmetic_count"], int)


def test_analysis_counts():
    """Analysis must identify meaningful counts of both types."""
    with open("/app/analysis.json") as f:
        data = json.load(f)
    cg = data["codegen_affecting_count"]
    cos = data["cosmetic_count"]
    assert cg >= 6, (
        f"codegen_affecting_count={cg} too low; expect at least 7"
    )
    assert cos >= 5, (
        f"cosmetic_count={cos} too low; expect at least 7"
    )
    assert cg + cos >= 12, (
        f"Total differences ({cg}+{cos}={cg+cos}) too low; expect at least 14"
    )


def test_cosmetic_subscript_preserved():
    """The cosmetic &data[off] form must be preserved."""
    with open("/app/candidate.c") as f:
        source = f.read()
    assert "&data[off]" in source, (
        "&data[off] was removed — this is a cosmetic difference "
        "(identical codegen to data + off) and should be left unchanged"
    )


def test_cosmetic_type_alias_preserved():
    """The cosmetic 'unsigned int' type in feistel_round must be preserved."""
    with open("/app/candidate.c") as f:
        source = f.read()
    feistel_start = source.find("feistel_round")
    assert feistel_start != -1, "feistel_round function not found"
    feistel_body = source[feistel_start:]
    assert "unsigned int" in feistel_body, (
        "'unsigned int' was changed in feistel_round — this is a cosmetic "
        "difference (uint32_t is a typedef for unsigned int) and should be "
        "left unchanged"
    )


def test_cosmetic_hex_case_preserved():
    """The cosmetic uppercase hex 0x5BD1E995 must be preserved."""
    with open("/app/candidate.c") as f:
        source = f.read()
    assert "0x5BD1E995" in source, (
        "0x5BD1E995 was changed — hex letter case is cosmetic "
        "(same integer constant) and should be left unchanged"
    )


def test_cosmetic_return_parens_preserved():
    """The cosmetic return (hash) form in hash_entries must be preserved."""
    with open("/app/candidate.c") as f:
        source = f.read()
    he_start = source.find("hash_entries")
    fr_start = source.find("feistel_round")
    assert he_start != -1, "hash_entries not found"
    assert fr_start != -1, "feistel_round not found"
    he_body = source[he_start:fr_start]
    assert re.search(r"return\s*\(hash\)", he_body), (
        "'return (hash)' was changed in hash_entries — parentheses around "
        "a return value are cosmetic and should be left unchanged"
    )

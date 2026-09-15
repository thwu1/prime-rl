
import os
import sys
import shutil
import importlib.util
import random
import pytest

ANSWER_FILE = "/app/answer.txt"


@pytest.fixture
def answers():
    assert os.path.exists(ANSWER_FILE), "{} does not exist".format(ANSWER_FILE)
    with open(ANSWER_FILE) as f:
        lines = [line.strip() for line in f if line.strip()]
    parsed = {}
    for line in lines:
        if "=" in line:
            key, val = line.split("=", 1)
            parsed[key.strip()] = val.strip()
    return parsed


# ========== answer.txt tests ==========

def test_answer_file_exists():
    assert os.path.exists(ANSWER_FILE), "answer.txt was not created"
    with open(ANSWER_FILE) as f:
        content = f.read().strip()
    assert len(content) > 0, "answer.txt is empty"


def test_has_all_keys(answers):
    required = {"version", "flag", "error_count", "integrity_token"}
    missing = required - set(answers.keys())
    assert not missing, "Missing keys: {}".format(missing)


def test_version(answers):
    assert answers.get("version") == "3.7.2-rc4", (
        "Expected version '3.7.2-rc4', got '{}'".format(answers.get("version"))
    )


def test_flag(answers):
    expected = "FLAG{l1n3ar1z3d_vfs_r3v3rs3_3ngin33r3d}"
    assert answers.get("flag") == expected, (
        "Expected flag '{}', got '{}'".format(expected, answers.get("flag"))
    )


def test_error_count(answers):
    assert answers.get("error_count") == "42", (
        "Expected error_count '42', got '{}'".format(answers.get("error_count"))
    )


def test_integrity_token(answers):
    assert answers.get("integrity_token") == "ECHO-7F3A9B2D", (
        "Expected integrity_token 'ECHO-7F3A9B2D', got '{}'".format(
            answers.get("integrity_token"))
    )


# ========== custom_hash.py tests ==========

def test_custom_hash_exists():
    assert os.path.exists("/app/custom_hash.py"), (
        "custom_hash.py was not created at /app/custom_hash.py"
    )


def test_custom_hash_no_cheating():
    """Verify custom_hash.py does not shell out to the hasher binary."""
    with open("/app/custom_hash.py") as f:
        source = f.read()
    banned = ["subprocess", "os.system", "os.popen", "vfs_hasher", "Popen"]
    for term in banned:
        assert term not in source, (
            "custom_hash.py must not contain '{}' -- "
            "implementation must be self-contained".format(term)
        )


def test_custom_hash_correctness():
    """Verify custom_hash.py matches pre-computed expected hashes on diverse inputs."""
    # Pre-computed expected hash values (deterministic from the SBOX embedded in the binary)
    rng = random.Random(0xBEEF)
    rand_vec = bytes(rng.randint(0, 255) for _ in range(137))

    test_cases = [
        (b"test", "84f8f99a"),
        (b"hello world", "489b47d7"),
        (b"\x00\x01\x02\x03\x04\x05\x06\x07", "60815083"),
        (b"LVFS", "8469f1c6"),
        (b"A" * 500, "470b8a62"),
        (bytes(range(256)), "0bb6ceff"),
        (rand_vec, "9d3502e2"),
    ]

    # Hide the binary so custom_hash.py cannot shell out to it
    hasher_path = "/app/vfs_hasher"
    backup_path = "/app/.vfs_hasher_hidden"
    moved = False
    if os.path.exists(hasher_path):
        shutil.move(hasher_path, backup_path)
        moved = True

    try:
        # Clear any cached module
        for key in list(sys.modules.keys()):
            if "custom_hash" in key:
                del sys.modules[key]

        spec = importlib.util.spec_from_file_location(
            "custom_hash", "/app/custom_hash.py"
        )
        assert spec is not None, "Could not load custom_hash.py"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert hasattr(mod, "custom_hash"), (
            "custom_hash.py must define a 'custom_hash' function"
        )
        assert callable(mod.custom_hash), (
            "'custom_hash' must be callable"
        )

        for i, (data, exp_hash) in enumerate(test_cases):
            result = mod.custom_hash(data)
            assert isinstance(result, int), (
                "custom_hash must return an int, got {}".format(type(result))
            )
            actual = "{:08x}".format(result)
            assert actual == exp_hash, (
                "Hash mismatch on test vector {} ({} bytes): "
                "expected={}, custom_hash={}".format(
                    i, len(data), exp_hash, actual)
            )
    finally:
        if moved and os.path.exists(backup_path):
            shutil.move(backup_path, hasher_path)

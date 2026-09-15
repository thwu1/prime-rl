"""
Tests for dm-verity forensic image analysis.
Verifies forensic report correctness, remediation functionality, and anti-cheat.
"""

import json
import os
import subprocess

import pytest

REPORT_PATH = "/app/report.json"
EXPECTED_PATH = "/var/verity/expected.json"
IMAGE_DIR = "/app/images"
MANIFEST_PATH = "/app/manifest.json"
REMEDIATE_PATH = "/app/remediate.sh"
REMEDIATION_JSON = "/app/remediation.json"
DATA_BLOCK_SIZE = 4096


@pytest.fixture(scope="session")
def expected():
    with open(EXPECTED_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def report():
    assert os.path.exists(REPORT_PATH), (
        f"Report file not found at {REPORT_PATH}. "
        "The tool must write results to /app/report.json."
    )
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def manifest():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


# ── Part 1: Forensic Report Tests ─────────────────────────────────


def test_report_structure(report):
    """Report must have an 'images' top-level key."""
    assert "images" in report, "Report missing top-level 'images' key"


def test_report_has_all_images(report, expected):
    """Every expected image must appear in the report."""
    for name in expected:
        assert name in report["images"], f"Missing image '{name}' in report"


def test_root_hashes(report, expected):
    """Computed root hashes must match known-good values."""
    for name, exp in expected.items():
        img = report["images"][name]
        assert "root_hash" in img, f"Missing root_hash for {name}"
        got = img["root_hash"].lower()
        want = exp["root_hash"].lower()
        assert got == want, (
            f"Root hash mismatch for {name}:\n"
            f"  got:  {got}\n"
            f"  want: {want}"
        )


def test_hash_algorithms(report, expected):
    """Reported hash algorithm must match for each image."""
    for name, exp in expected.items():
        img = report["images"][name]
        assert "hash_algorithm" in img, f"Missing hash_algorithm for {name}"
        assert img["hash_algorithm"] == exp["hash_algorithm"], (
            f"Algorithm mismatch for {name}: "
            f"got '{img['hash_algorithm']}', expected '{exp['hash_algorithm']}'"
        )


def test_integrity_status(report, expected):
    """Integrity field must correctly indicate clean vs corrupted."""
    for name, exp in expected.items():
        img = report["images"][name]
        assert "integrity" in img, f"Missing integrity for {name}"
        assert img["integrity"] == exp["status"], (
            f"Status mismatch for {name}: "
            f"got '{img['integrity']}', expected '{exp['status']}'"
        )


def test_corrupted_blocks_exact(report, expected):
    """Corrupted block index lists must match exactly."""
    for name, exp in expected.items():
        img = report["images"][name]
        got = sorted(img.get("corrupted_data_blocks", []))
        want = sorted(exp["corrupted_data_blocks"])
        assert got == want, (
            f"Corrupted blocks mismatch for {name}:\n"
            f"  got:  {got}\n"
            f"  want: {want}"
        )


# ── Cross-validation with veritysetup ─────────────────────────────


def test_clean_images_pass_veritysetup(report, expected, manifest):
    """Clean images' reported root hashes must pass veritysetup verify."""
    for name, exp in expected.items():
        if exp["status"] != "clean":
            continue
        img = report["images"][name]
        path = os.path.join(IMAGE_DIR, name)
        ho = manifest[name]["hash_offset"]
        result = subprocess.run(
            [
                "veritysetup",
                "verify",
                "--hash-offset",
                str(ho),
                path,
                path,
                img["root_hash"],
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"veritysetup verify failed for clean image {name} "
            f"with reported root hash {img['root_hash']}: {result.stderr}"
        )


def test_corrupted_images_fail_veritysetup(expected, manifest):
    """Corrupted images must fail veritysetup verify with original root hash."""
    for name, exp in expected.items():
        if exp["status"] != "corrupted":
            continue
        path = os.path.join(IMAGE_DIR, name)
        ho = manifest[name]["hash_offset"]
        result = subprocess.run(
            [
                "veritysetup",
                "verify",
                "--hash-offset",
                str(ho),
                path,
                path,
                exp["root_hash"],
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"veritysetup verify should have FAILED for corrupted image {name}"
        )


# ── Part 2: Remediation Tests ─────────────────────────────────────


def test_remediation_script_exists():
    """remediate.sh must exist and be a shell script."""
    assert os.path.exists(REMEDIATE_PATH), f"{REMEDIATE_PATH} not found"
    with open(REMEDIATE_PATH) as f:
        first_line = f.readline().strip()
    assert first_line.startswith("#!"), "remediate.sh missing shebang line"


def test_remediation_uses_veritysetup():
    """remediate.sh must use veritysetup format for hash tree rebuilding."""
    with open(REMEDIATE_PATH) as f:
        content = f.read()
    assert "veritysetup" in content, "remediate.sh must invoke veritysetup"
    assert "format" in content, "remediate.sh must call veritysetup format"


@pytest.fixture(scope="session")
def remediation_result():
    """Run remediate.sh and return its subprocess result."""
    result = subprocess.run(
        ["bash", REMEDIATE_PATH],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=120,
    )
    return result


def test_remediation_runs_successfully(remediation_result):
    """remediate.sh must exit with code 0."""
    assert remediation_result.returncode == 0, (
        f"remediate.sh failed:\nstdout: {remediation_result.stdout}\n"
        f"stderr: {remediation_result.stderr}"
    )


def test_remediation_json_exists(remediation_result):
    """remediation.json must exist after running remediate.sh."""
    assert os.path.exists(REMEDIATION_JSON), (
        f"{REMEDIATION_JSON} not found after running remediate.sh"
    )


def test_remediation_has_all_corrupted(remediation_result, expected):
    """remediation.json must contain entries for all corrupted images."""
    assert os.path.exists(REMEDIATION_JSON), "remediation.json missing"
    with open(REMEDIATION_JSON) as f:
        remediation = json.load(f)
    for name, exp in expected.items():
        if exp["status"] != "corrupted":
            continue
        assert name in remediation, (
            f"Corrupted image '{name}' missing from remediation.json"
        )
        assert len(remediation[name]) > 0, (
            f"Empty root hash for '{name}' in remediation.json"
        )


def test_remediation_veritysetup_verify(remediation_result, expected, manifest):
    """After remediation, all previously-corrupted images must pass veritysetup verify."""
    assert os.path.exists(REMEDIATION_JSON), "remediation.json missing"
    with open(REMEDIATION_JSON) as f:
        remediation = json.load(f)

    for name, exp in expected.items():
        if exp["status"] != "corrupted":
            continue
        assert name in remediation, f"Missing {name} in remediation.json"
        new_root = remediation[name]
        path = os.path.join(IMAGE_DIR, name)
        ho = manifest[name]["hash_offset"]
        result = subprocess.run(
            [
                "veritysetup",
                "verify",
                "--hash-offset",
                str(ho),
                path,
                path,
                new_root,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"veritysetup verify failed for remediated image {name} "
            f"with new root hash {new_root}: {result.stderr}"
        )


# ── Anti-cheat: fresh image at test time ───────────────────────────


def test_z_fresh_image_verification():
    """
    Generate a brand-new image at test time with non-default parameters,
    run the tool, and verify correct analysis. Prevents hardcoded answers.
    """
    fresh_name = "fresh_anticheat.img"
    fresh_path = os.path.join(IMAGE_DIR, fresh_name)
    num_blocks = 64
    data_size = num_blocks * DATA_BLOCK_SIZE
    corrupt_idx = 10
    hash_alg = "sha512"

    # Create image with unique content pattern
    with open(fresh_path, "wb") as f:
        for i in range(num_blocks):
            block = bytes(
                [(i * 11 + j * 17 + 99) % 256 for j in range(DATA_BLOCK_SIZE)]
            )
            f.write(block)

    # Format with veritysetup (random salt, sha512)
    fmt = subprocess.run(
        [
            "veritysetup",
            "format",
            "--hash-offset",
            str(data_size),
            "--data-block-size",
            str(DATA_BLOCK_SIZE),
            "--hash-block-size",
            str(DATA_BLOCK_SIZE),
            "--hash",
            hash_alg,
            fresh_path,
            fresh_path,
        ],
        capture_output=True,
        text=True,
    )
    assert fmt.returncode == 0, f"veritysetup format failed: {fmt.stderr}"

    expected_root = None
    for line in fmt.stdout.splitlines():
        if "Root hash:" in line:
            expected_root = line.split(":", 1)[1].strip().lower()
    assert expected_root is not None, "Could not parse root hash from veritysetup"

    # Corrupt one data block
    with open(fresh_path, "r+b") as f:
        f.seek(corrupt_idx * DATA_BLOCK_SIZE)
        f.write(b"\xde\xad" * (DATA_BLOCK_SIZE // 2))

    # Add to manifest
    with open(MANIFEST_PATH) as f:
        manifest_data = json.load(f)
    manifest_data[fresh_name] = {
        "hash_offset": data_size,
        "description": "Anti-cheat fresh image",
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest_data, f, indent=2)

    # Re-run the tool
    run = subprocess.run(
        ["python3", "/app/verity_forensics.py"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert run.returncode == 0, f"Tool failed on fresh image:\n{run.stderr}"

    # Load updated report
    with open(REPORT_PATH) as f:
        new_report = json.load(f)

    assert fresh_name in new_report["images"], (
        f"Fresh image '{fresh_name}' missing from report after re-run"
    )
    fresh = new_report["images"][fresh_name]

    # Verify root hash matches veritysetup output
    assert fresh["root_hash"].lower() == expected_root, (
        f"Fresh root hash mismatch: got {fresh['root_hash']}, want {expected_root}"
    )

    # Verify algorithm detection
    assert fresh["hash_algorithm"] == hash_alg, (
        f"Fresh algorithm mismatch: got {fresh['hash_algorithm']}, want {hash_alg}"
    )

    # Verify corruption detection
    assert fresh["integrity"] == "corrupted", (
        f"Fresh image should be corrupted, got '{fresh['integrity']}'"
    )
    assert sorted(fresh["corrupted_data_blocks"]) == [corrupt_idx], (
        f"Fresh corrupted blocks: got {fresh['corrupted_data_blocks']}, "
        f"want [{corrupt_idx}]"
    )

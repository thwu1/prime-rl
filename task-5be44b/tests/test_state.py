
import os
import json
import subprocess

EXPECTED_PLAINTEXT = b"R3v3rs3_Th3_VM!!"


def test_answer_file_exists():
    assert os.path.isfile("/app/answer.txt"), "/app/answer.txt does not exist"


def test_answer_content():
    with open("/app/answer.txt", "rb") as f:
        content = f.read()
    content_stripped = content.rstrip(b"\n\r ")
    assert content_stripped == EXPECTED_PLAINTEXT, (
        f"Expected {EXPECTED_PLAINTEXT!r}, got {content_stripped!r}"
    )


def test_answer_length():
    with open("/app/answer.txt", "rb") as f:
        content = f.read().rstrip(b"\n\r ")
    assert len(content) == 16, f"Expected 16 bytes, got {len(content)}"


def test_report_file_exists():
    assert os.path.isfile("/app/report.json"), "/app/report.json does not exist"


def test_report_structure():
    with open("/app/report.json", "r") as f:
        report = json.load(f)
    assert "selected_candidate" in report, "report.json missing required key: selected_candidate"
    assert isinstance(report["selected_candidate"], str) and len(report["selected_candidate"]) >= 4, (
        f"report.json['selected_candidate'] must be a non-empty candidate name (>=4 chars)"
    )
    description_keys = [
        "alpha_description",
        "beta_description",
        "gamma_description",
        "evidence",
    ]
    for key in description_keys:
        assert key in report, f"report.json missing required key: {key}"
        assert isinstance(report[key], str) and len(report[key]) > 10, (
            f"report.json['{key}'] must be a non-trivial string (>10 chars)"
        )


def test_report_correct_candidate():
    with open("/app/report.json", "r") as f:
        report = json.load(f)
    assert report["selected_candidate"] == "alpha", (
        f"Expected selected_candidate='alpha', got {report['selected_candidate']!r}"
    )


def test_reencryption_matches():
    """Re-encrypt the answer through the VM with alpha.bin and verify it matches."""
    with open("/app/answer.txt", "rb") as f:
        plaintext = f.read().rstrip(b"\n\r ")

    with open("/tmp/test_input.bin", "wb") as f:
        f.write(plaintext)

    result = subprocess.run(
        ["/app/vm", "/app/candidates/alpha.bin",
         "/tmp/test_input.bin", "/tmp/test_output.bin"],
        capture_output=True, timeout=30
    )
    assert result.returncode == 0, f"VM execution failed: {result.stderr.decode()}"

    with open("/tmp/test_output.bin", "rb") as f:
        reencrypted = f.read()
    with open("/app/encrypted.bin", "rb") as f:
        expected_ct = f.read()

    assert reencrypted == expected_ct, (
        f"Re-encryption mismatch: {reencrypted.hex()} != {expected_ct.hex()}"
    )

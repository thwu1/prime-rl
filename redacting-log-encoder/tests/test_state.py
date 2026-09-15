
import subprocess
import os
import json


def _run(cmd, cwd="/app", timeout=180):
    """Run a command and return the result."""
    return subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )


def _setup_once():
    """Ensure dependencies are resolved and test file is in place."""
    os.makedirs("/app/redact", exist_ok=True)
    subprocess.run(
        "cp /tests/redact_test.go /app/redact/redact_test.go",
        shell=True, capture_output=True,
    )
    subprocess.run(
        "cd /app && go mod tidy",
        shell=True, cwd="/app", capture_output=True, timeout=120,
    )


_setup_once()


def test_go_build_succeeds():
    """The redact package must compile without errors."""
    r = _run("go build ./redact/")
    assert r.returncode == 0, f"Build failed:\n{r.stderr}"


def test_top_level_mask():
    """Top-level string field masking must work."""
    r = _run("go test -v -count=1 -run TestTopLevelMask ./redact/")
    assert r.returncode == 0, f"TestTopLevelMask failed:\n{r.stdout}\n{r.stderr}"


def test_top_level_drop():
    """Top-level field dropping must work."""
    r = _run("go test -v -count=1 -run TestTopLevelDrop ./redact/")
    assert r.returncode == 0, f"TestTopLevelDrop failed:\n{r.stdout}\n{r.stderr}"


def test_nested_object_mask():
    """Fields inside nested objects must be redacted."""
    r = _run("go test -v -count=1 -run TestNestedObjectMask ./redact/")
    assert r.returncode == 0, f"TestNestedObjectMask failed:\n{r.stdout}\n{r.stderr}"


def test_deep_nested_mask():
    """Three-level-deep nested fields must be redacted."""
    r = _run("go test -v -count=1 -run TestDeepNestedMask ./redact/")
    assert r.returncode == 0, f"TestDeepNestedMask failed:\n{r.stdout}\n{r.stderr}"


def test_wildcard_match():
    """Wildcard patterns must match at correct nesting depth."""
    r = _run("go test -v -count=1 -run TestWildcardMatch ./redact/")
    assert r.returncode == 0, f"TestWildcardMatch failed:\n{r.stdout}\n{r.stderr}"


def test_clone_preserves_redaction():
    """Clone must return a working redacting encoder."""
    r = _run("go test -v -count=1 -run TestClonePreservesRedaction ./redact/")
    assert r.returncode == 0, f"TestClonePreservesRedaction failed:\n{r.stdout}\n{r.stderr}"


def test_encode_entry_redaction():
    """EncodeEntry must apply redaction to entry-level fields."""
    r = _run("go test -v -count=1 -run TestEncodeEntryRedaction ./redact/")
    assert r.returncode == 0, f"TestEncodeEntryRedaction failed:\n{r.stdout}\n{r.stderr}"


def test_encode_entry_nested_object():
    """EncodeEntry must redact nested object fields."""
    r = _run("go test -v -count=1 -run TestEncodeEntryWithNestedObject ./redact/")
    assert r.returncode == 0, f"TestEncodeEntryWithNestedObject failed:\n{r.stdout}\n{r.stderr}"


def test_encode_entry_idempotent():
    """EncodeEntry must be idempotent across repeated calls."""
    r = _run("go test -v -count=1 -run TestEncodeEntryIdempotent ./redact/")
    assert r.returncode == 0, f"TestEncodeEntryIdempotent failed:\n{r.stdout}\n{r.stderr}"


def test_array_object_redaction():
    """Objects inside arrays must have fields redacted."""
    r = _run("go test -v -count=1 -run TestArrayObjectRedaction ./redact/")
    assert r.returncode == 0, f"TestArrayObjectRedaction failed:\n{r.stdout}\n{r.stderr}"


def test_namespace_tracking():
    """OpenNamespace must affect redaction rule matching."""
    r = _run("go test -v -count=1 -run TestNamespaceTracking ./redact/")
    assert r.returncode == 0, f"TestNamespaceTracking failed:\n{r.stdout}\n{r.stderr}"


def test_multiple_rules():
    """Multiple rules at different depths must all apply correctly."""
    r = _run("go test -v -count=1 -run TestMultipleRules ./redact/")
    assert r.returncode == 0, f"TestMultipleRules failed:\n{r.stdout}\n{r.stderr}"


def test_all_go_tests_pass():
    """All Go tests in the redact package must pass."""
    r = _run("go test -v -count=1 ./redact/")
    assert r.returncode == 0, f"Go tests failed:\n{r.stdout}\n{r.stderr}"
    assert "FAIL" not in r.stdout, f"Some tests failed:\n{r.stdout}"

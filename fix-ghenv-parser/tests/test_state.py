
import subprocess
import json
import os
import tempfile
import pytest

GHENV = "/app/ghenv.sh"


def run_ghenv(*args):
    return subprocess.run(
        [GHENV] + list(args),
        capture_output=True, text=True, timeout=30
    )


def _write_temp(content, suffix=".env"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def parse_content(content):
    path = _write_temp(content)
    try:
        return run_ghenv("parse", path)
    finally:
        os.unlink(path)


def encode_pairs(pairs):
    path = _write_temp(json.dumps(pairs), suffix=".json")
    try:
        return run_ghenv("encode", path)
    finally:
        os.unlink(path)


def validate_content(content):
    path = _write_temp(content)
    try:
        return run_ghenv("validate", path)
    finally:
        os.unlink(path)


def roundtrip_pairs(pairs):
    path = _write_temp(json.dumps(pairs), suffix=".json")
    try:
        return run_ghenv("roundtrip", path)
    finally:
        os.unlink(path)


# ======================================================================
# Parser — simple format
# ======================================================================

class TestParserSimple:
    def test_single_pair(self):
        r = parse_content("key=value\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 1
        assert data[0] == {"key": "key", "value": "value"}

    def test_multiple_pairs(self):
        r = parse_content("a=1\nb=2\nc=3\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 3
        assert data[0] == {"key": "a", "value": "1"}
        assert data[1] == {"key": "b", "value": "2"}
        assert data[2] == {"key": "c", "value": "3"}

    def test_empty_value(self):
        r = parse_content("key=\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "key", "value": ""}

    def test_value_with_equals(self):
        """Split on first '=', not last. Value 'val=ue=end' must be preserved."""
        r = parse_content("key=val=ue=end\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "key", "value": "val=ue=end"}

    def test_value_with_double_angle(self):
        """'=' before '<<' means simple format — value includes '<<'."""
        r = parse_content("key=val<<EOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "key", "value": "val<<EOF"}


# ======================================================================
# Parser — heredoc format
# ======================================================================

class TestParserHeredoc:
    def test_single_line_heredoc(self):
        r = parse_content("key<<EOF\nvalue\nEOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "key", "value": "value"}

    def test_multiline_heredoc(self):
        r = parse_content("key<<DELIM\nline1\nline2\nline3\nDELIM\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "key", "value": "line1\nline2\nline3"}

    def test_empty_heredoc(self):
        r = parse_content("key<<EOF\nEOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "key", "value": ""}

    def test_heredoc_delimiter_at_eof_no_trailing_newline(self):
        """Delimiter at EOF without trailing newline is valid."""
        r = parse_content("key<<EOF\nvalue\nEOF")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "key", "value": "value"}


# ======================================================================
# Parser — precedence rule
# ======================================================================

class TestParserPrecedence:
    def test_equals_before_heredoc(self):
        """'=' at index 1, '<<' at index 3 => simple format."""
        r = parse_content("a=b<<c\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "a", "value": "b<<c"}

    def test_heredoc_before_equals(self):
        """'<<' at index 1, '=' at index 8 => heredoc format."""
        r = parse_content("a<<DELIM=x\nthe value\nDELIM=x\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data[0] == {"key": "a", "value": "the value"}


# ======================================================================
# Parser — empty line handling
# ======================================================================

class TestParserEmptyLines:
    def test_empty_lines_skipped(self):
        r = parse_content("\nkey=value\n\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 1
        assert data[0] == {"key": "key", "value": "value"}

    def test_empty_lines_between_pairs(self):
        r = parse_content("a=1\n\nb=2\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 2
        assert data[0] == {"key": "a", "value": "1"}
        assert data[1] == {"key": "b", "value": "2"}


# ======================================================================
# Parser — mixed entries
# ======================================================================

class TestParserMixed:
    def test_mixed_simple_and_heredoc(self):
        content = "simple=value\n\nmulti<<DELIM\nline1\nline2\nDELIM\n\nanother=pair\n"
        r = parse_content(content)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 3
        assert data[0] == {"key": "simple", "value": "value"}
        assert data[1] == {"key": "multi", "value": "line1\nline2"}
        assert data[2] == {"key": "another", "value": "pair"}


# ======================================================================
# Parser — error conditions
# ======================================================================

class TestParserErrors:
    def test_missing_delimiter(self):
        r = parse_content("key<<EOF\nvalue\n")
        assert r.returncode != 0

    def test_eof_marker_missing_newline(self):
        """Content at EOF without trailing newline in heredoc should produce
        the 'EOF marker missing new line' error, not 'delimiter not found'."""
        r = parse_content("key<<EOF\nvalue")
        assert r.returncode != 0
        stderr_lower = r.stderr.lower()
        assert "missing" in stderr_lower

    def test_empty_key_heredoc(self):
        r = parse_content("<<EOF\nvalue\nEOF\n")
        assert r.returncode != 0

    def test_empty_delimiter(self):
        r = parse_content("key<<\nvalue\n\n")
        assert r.returncode != 0

    def test_no_format_marker(self):
        r = parse_content("just_a_bare_line\n")
        assert r.returncode != 0


# ======================================================================
# Encoder
# ======================================================================

class TestEncoder:
    def test_simple_encode(self):
        r = encode_pairs([{"key": "a", "value": "1"}])
        assert r.returncode == 0
        assert "a=1" in r.stdout

    def test_multiline_encode(self):
        r = encode_pairs([{"key": "k", "value": "line1\nline2"}])
        assert r.returncode == 0
        assert "<<" in r.stdout

    def test_delimiter_collision(self):
        """When value contains 'EOF' as a complete line, encoder must choose
        a different delimiter so the output parses back correctly."""
        pairs = [{"key": "k", "value": "before\nEOF\nafter"}]
        r = encode_pairs(pairs)
        assert r.returncode == 0
        # Parse the encoded output back
        path = _write_temp(r.stdout)
        try:
            r2 = run_ghenv("parse", path)
        finally:
            os.unlink(path)
        assert r2.returncode == 0
        data = json.loads(r2.stdout)
        assert data[0]["value"] == "before\nEOF\nafter"


# ======================================================================
# Validator
# ======================================================================

class TestValidator:
    def test_valid_simple(self):
        r = validate_content("key=value\n")
        assert r.returncode == 0

    def test_valid_heredoc(self):
        r = validate_content("key<<EOF\nvalue\nEOF\n")
        assert r.returncode == 0

    def test_invalid_format(self):
        r = validate_content("no_equals_or_heredoc\n")
        assert r.returncode != 0

    def test_reports_line_numbers(self):
        r = validate_content("ok=fine\nbad_line\nalso=ok\n")
        assert r.returncode != 0
        assert "line 2" in r.stderr

    def test_reports_multiple_errors(self):
        """Must report ALL errors, not stop at the first."""
        r = validate_content("bad1\nbad2\n")
        assert r.returncode != 0
        assert "line 1" in r.stderr
        assert "line 2" in r.stderr

    def test_validate_heredoc_missing_delimiter(self):
        r = validate_content("key<<EOF\nvalue\n")
        assert r.returncode != 0


# ======================================================================
# Round-trip
# ======================================================================

class TestRoundtrip:
    def test_simple_roundtrip(self):
        pairs = [{"key": "a", "value": "hello"}, {"key": "b", "value": "world"}]
        r = roundtrip_pairs(pairs)
        assert r.returncode == 0
        assert "PASS" in r.stdout

    def test_multiline_roundtrip(self):
        pairs = [{"key": "data", "value": "line1\nline2\nline3"}]
        r = roundtrip_pairs(pairs)
        assert r.returncode == 0
        assert "PASS" in r.stdout

    def test_adversarial_roundtrip(self):
        """Content containing delimiter-like strings must round-trip safely."""
        pairs = [
            {"key": "tricky", "value": "line1\nEOF\nline3"},
            {"key": "also_tricky", "value": "has=equals\nand<<heredoc\nmarkers"},
        ]
        r = roundtrip_pairs(pairs)
        assert r.returncode == 0
        assert "PASS" in r.stdout

    def test_special_chars_roundtrip(self):
        pairs = [
            {"key": "json_val", "value": '{"nested": "json", "arr": [1,2,3]}'},
            {"key": "spaces", "value": "  leading and trailing  "},
            {"key": "tabs", "value": "col1\tcol2\tcol3"},
        ]
        r = roundtrip_pairs(pairs)
        assert r.returncode == 0
        assert "PASS" in r.stdout

    def test_empty_value_roundtrip(self):
        pairs = [{"key": "empty", "value": ""}]
        r = roundtrip_pairs(pairs)
        assert r.returncode == 0
        assert "PASS" in r.stdout

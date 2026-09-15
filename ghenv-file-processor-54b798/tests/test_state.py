"""
Tests for /app/runner-env.sh — CI Step Environment State Manager.

Verifies parsing, encoding, validation, round-trip fidelity, SQLite
storage, HMAC-SHA256 integrity verification, multiline-safe queries,
and concurrent-safe flock-based append operations.

"""

import hashlib
import hmac as hmac_mod
import json
import os
import sqlite3 as sqlite3_mod
import subprocess
import tempfile
import time

import pytest

RUNNER = "/app/runner-env.sh"


def run_runner(*args):
    """Run runner-env.sh with the given arguments."""
    result = subprocess.run(
        ["bash", RUNNER, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result


def parse_content(content):
    """Write content to a temp file and run 'parse' on it."""
    fd, path = tempfile.mkstemp(suffix=".env")
    try:
        with os.fdopen(fd, "wb") as f:
            if isinstance(content, str):
                f.write(content.encode("utf-8"))
            else:
                f.write(content)
        return run_runner("parse", path)
    finally:
        os.unlink(path)


def encode_pairs(pairs):
    """Encode pairs via runner-env.sh and return (result, file_content)."""
    fd_json, json_path = tempfile.mkstemp(suffix=".json")
    fd_out, out_path = tempfile.mkstemp(suffix=".env")
    os.close(fd_out)
    try:
        with os.fdopen(fd_json, "w") as f:
            json.dump(pairs, f)
        result = run_runner("encode", json_path, out_path)
        content = None
        if result.returncode == 0 and os.path.exists(out_path):
            with open(out_path, "r") as f:
                content = f.read()
        return result, content
    finally:
        os.unlink(json_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


def round_trip(pairs):
    """Encode pairs, then parse the result, and return parsed data."""
    fd_json, json_path = tempfile.mkstemp(suffix=".json")
    fd_out, out_path = tempfile.mkstemp(suffix=".env")
    os.close(fd_out)
    try:
        with os.fdopen(fd_json, "w") as f:
            json.dump(pairs, f)
        r1 = run_runner("encode", json_path, out_path)
        assert r1.returncode == 0, f"Encode failed: {r1.stderr}"
        r2 = run_runner("parse", out_path)
        assert r2.returncode == 0, f"Parse failed: {r2.stderr}"
        return json.loads(r2.stdout)
    finally:
        os.unlink(json_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


# ── Parse: simple format ──────────────────────────────────────────


class TestParseSimple:
    def test_basic_key_value(self):
        r = parse_content("name=value\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "name", "value": "value"}]

    def test_value_with_equals(self):
        r = parse_content("key=val=ue=more\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "val=ue=more"}]

    def test_empty_value(self):
        r = parse_content("key=\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": ""}]

    def test_multiple_simple_entries(self):
        r = parse_content("a=1\nb=2\nc=3\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 3
        assert data[0] == {"key": "a", "value": "1"}
        assert data[1] == {"key": "b", "value": "2"}
        assert data[2] == {"key": "c", "value": "3"}

    def test_value_contains_heredoc_marker(self):
        """Simple format when value contains << (= appears first)."""
        r = parse_content("key=a<<b\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "a<<b"}]


# ── Parse: heredoc format ─────────────────────────────────────────


class TestParseHeredoc:
    def test_basic_heredoc(self):
        r = parse_content("key<<EOF\nhello\nworld\nEOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "hello\nworld"}]

    def test_heredoc_single_line_value(self):
        r = parse_content("key<<END\nsingle line\nEND\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "single line"}]

    def test_heredoc_empty_value(self):
        r = parse_content("key<<EOF\nEOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": ""}]

    def test_heredoc_custom_delimiter(self):
        r = parse_content("key<<MYDELIM\nvalue here\nMYDELIM\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "value here"}]

    def test_heredoc_value_with_equals(self):
        r = parse_content("key<<EOF\na=b\nc=d\nEOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "a=b\nc=d"}]

    def test_heredoc_value_with_empty_lines(self):
        """Empty lines inside heredoc are part of the value."""
        r = parse_content("key<<EOF\nfirst\n\nthird\nEOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "first\n\nthird"}]

    def test_delimiter_substring_in_value_not_on_own_line(self):
        """Delimiter must match the full line, not a substring."""
        r = parse_content("key<<EOF\nline with EOF in it\nEOF\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "line with EOF in it"}]


# ── Parse: precedence of = vs << ──────────────────────────────────


class TestParsePrecedence:
    def test_equals_before_heredoc_marker(self):
        """If = appears before <<, treat as simple format."""
        r = parse_content("a=b<<c\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "a", "value": "b<<c"}]

    def test_heredoc_before_equals(self):
        """If << appears before =, treat as heredoc format."""
        content = "a<<DELIM=extra\nhello\nDELIM=extra\n"
        r = parse_content(content)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "a", "value": "hello"}]

    def test_heredoc_delimiter_contains_equals(self):
        content = "key<<END=MARKER\nsome value\nEND=MARKER\n"
        r = parse_content(content)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "some value"}]

    def test_adjacent_markers_heredoc_first(self):
        """<< at position 1, = at position 5: should be heredoc."""
        content = "x<<D=Z\nval\nD=Z\n"
        r = parse_content(content)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "x", "value": "val"}]


# ── Parse: empty-line handling ────────────────────────────────────


class TestParseEmptyLines:
    def test_empty_lines_between_entries(self):
        r = parse_content("\na=1\n\nb=2\n\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 2
        assert data[0] == {"key": "a", "value": "1"}
        assert data[1] == {"key": "b", "value": "2"}

    def test_leading_empty_lines(self):
        r = parse_content("\n\nkey=value\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "value"}]

    def test_only_empty_lines(self):
        r = parse_content("\n\n\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == []


# ── Parse: error conditions ───────────────────────────────────────


class TestParseErrors:
    def test_unterminated_heredoc(self):
        r = parse_content("key<<EOF\nvalue line\nno closing\n")
        assert r.returncode == 1
        assert r.stderr.strip() != ""

    def test_unterminated_heredoc_no_content(self):
        r = parse_content("key<<EOF\n")
        assert r.returncode == 1

    def test_empty_key_simple(self):
        r = parse_content("=value\n")
        assert r.returncode == 1

    def test_empty_delimiter(self):
        r = parse_content("key<<\nvalue\n")
        assert r.returncode == 1

    def test_empty_key_heredoc(self):
        r = parse_content("<<EOF\nvalue\nEOF\n")
        assert r.returncode == 1


# ── Parse: edge cases ─────────────────────────────────────────────


class TestParseEdgeCases:
    def test_no_trailing_newline_simple(self):
        """File ends without \\n — must still parse the last entry."""
        r = parse_content("key=value")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "value"}]

    def test_no_trailing_newline_multiple(self):
        r = parse_content("a=1\nb=2")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 2
        assert data[1] == {"key": "b", "value": "2"}

    def test_heredoc_delimiter_no_trailing_newline(self):
        """Delimiter on last line without \\n — must still close heredoc."""
        r = parse_content("key<<EOF\nhello\nEOF")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "key", "value": "hello"}]

    def test_mixed_simple_and_heredoc(self):
        content = "simple=value\nherkey<<EOF\nline1\nline2\nEOF\nanother=pair\n"
        r = parse_content(content)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) == 3
        assert data[0] == {"key": "simple", "value": "value"}
        assert data[1] == {"key": "herkey", "value": "line1\nline2"}
        assert data[2] == {"key": "another", "value": "pair"}

    def test_empty_file(self):
        r = parse_content("")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == []

    def test_nonexistent_file(self):
        r = run_runner("parse", "/nonexistent/file/path")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == []

    def test_value_with_single_quotes(self):
        """Values containing single quotes must parse correctly."""
        r = parse_content("msg=it's a test\n")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data == [{"key": "msg", "value": "it's a test"}]


# ── Encode ────────────────────────────────────────────────────────


class TestEncode:
    def test_simple_values(self):
        pairs = [{"key": "a", "value": "1"}, {"key": "b", "value": "2"}]
        result, content = encode_pairs(pairs)
        assert result.returncode == 0
        assert "a=1" in content
        assert "b=2" in content

    def test_multiline_uses_heredoc(self):
        pairs = [{"key": "msg", "value": "hello\nworld"}]
        result, content = encode_pairs(pairs)
        assert result.returncode == 0
        assert "<<" in content

    def test_delimiter_collision_avoided(self):
        """When value contains 'EOF' on its own line, encoder must pick
        a different delimiter so that parsing recovers the original value."""
        pairs = [{"key": "data", "value": "line1\nEOF\nline2"}]
        result, content = encode_pairs(pairs)
        assert result.returncode == 0
        fd, path = tempfile.mkstemp(suffix=".env")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            pr = run_runner("parse", path)
            assert pr.returncode == 0
            data = json.loads(pr.stdout)
            assert data == [{"key": "data", "value": "line1\nEOF\nline2"}]
        finally:
            os.unlink(path)


# ── Round-trip fidelity ───────────────────────────────────────────


class TestRoundTrip:
    def test_simple_value(self):
        pairs = [{"key": "x", "value": "hello"}]
        assert round_trip(pairs) == pairs

    def test_multiline_value(self):
        pairs = [{"key": "body", "value": "line1\nline2\nline3"}]
        assert round_trip(pairs) == pairs

    def test_value_with_equals(self):
        pairs = [{"key": "cmd", "value": "a=b=c"}]
        assert round_trip(pairs) == pairs

    def test_value_with_heredoc_marker(self):
        pairs = [{"key": "data", "value": "x<<y"}]
        assert round_trip(pairs) == pairs

    def test_eof_string_in_multiline_value(self):
        pairs = [{"key": "script", "value": "start\nEOF\nend"}]
        assert round_trip(pairs) == pairs

    def test_multiple_eof_variants(self):
        pairs = [{"key": "complex", "value": "EOF\nEOF_1\nEOF_2\ndata"}]
        assert round_trip(pairs) == pairs

    def test_multiple_mixed_entries(self):
        pairs = [
            {"key": "a", "value": "1"},
            {"key": "msg", "value": "hello\nworld"},
            {"key": "b", "value": "2"},
        ]
        assert round_trip(pairs) == pairs

    def test_empty_value(self):
        pairs = [{"key": "empty", "value": ""}]
        assert round_trip(pairs) == pairs

    def test_special_characters(self):
        pairs = [{"key": "special", "value": "tab\there & 'quotes' \"double\""}]
        assert round_trip(pairs) == pairs

    def test_value_is_single_newline(self):
        pairs = [{"key": "nl", "value": "\n"}]
        assert round_trip(pairs) == pairs

    def test_value_with_trailing_newline(self):
        pairs = [{"key": "trail", "value": "hello\n"}]
        assert round_trip(pairs) == pairs


# ── Validate ──────────────────────────────────────────────────────


class TestValidate:
    def test_valid_simple_file(self):
        fd, path = tempfile.mkstemp(suffix=".env")
        with os.fdopen(fd, "w") as f:
            f.write("key=value\n")
        try:
            r = run_runner("validate", path)
            assert r.returncode == 0
        finally:
            os.unlink(path)

    def test_valid_heredoc_file(self):
        fd, path = tempfile.mkstemp(suffix=".env")
        with os.fdopen(fd, "w") as f:
            f.write("key<<EOF\nvalue\nEOF\n")
        try:
            r = run_runner("validate", path)
            assert r.returncode == 0
        finally:
            os.unlink(path)

    def test_invalid_unterminated_heredoc(self):
        fd, path = tempfile.mkstemp(suffix=".env")
        with os.fdopen(fd, "w") as f:
            f.write("key<<EOF\nvalue\n")
        try:
            r = run_runner("validate", path)
            assert r.returncode == 1
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        r = run_runner("validate", "/nonexistent/file/path")
        assert r.returncode == 1


# ── Init ──────────────────────────────────────────────────────────


class TestInit:
    def test_creates_table(self):
        db_path = tempfile.mktemp(suffix=".db")
        try:
            r = run_runner("init", db_path)
            assert r.returncode == 0
            conn = sqlite3_mod.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='outputs';"
            )
            assert cursor.fetchone() is not None
            conn.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_idempotent_init(self):
        db_path = tempfile.mktemp(suffix=".db")
        try:
            run_runner("init", db_path)
            r = run_runner("init", db_path)
            assert r.returncode == 0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ── Store ─────────────────────────────────────────────────────────


class TestStore:
    def test_store_and_query_simple(self):
        """Store and query simple key-value pairs."""
        db_path = tempfile.mktemp(suffix=".db")
        env_path = tempfile.mktemp(suffix=".env")
        try:
            run_runner("init", db_path)
            with open(env_path, "w") as f:
                f.write("name=alice\nage=30\n")
            r = run_runner("store", db_path, "step1", env_path, "key123")
            assert r.returncode == 0

            r = run_runner("query", db_path, "step1")
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert len(data) == 2
            values = {d["key"]: d["value"] for d in data}
            assert values["name"] == "alice"
            assert values["age"] == "30"
        finally:
            for f in [db_path, env_path]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_store_values_with_single_quotes(self):
        """Values containing single quotes must not corrupt the database."""
        db_path = tempfile.mktemp(suffix=".db")
        env_path = tempfile.mktemp(suffix=".env")
        try:
            run_runner("init", db_path)
            with open(env_path, "w") as f:
                f.write("greeting=it's a test\n")
            r = run_runner("store", db_path, "step1", env_path, "secret")
            assert r.returncode == 0, f"Store failed: {r.stderr}"

            r = run_runner("query", db_path, "step1", "greeting")
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert len(data) == 1
            assert data[0]["value"] == "it's a test"
        finally:
            for f in [db_path, env_path]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_store_hmac_is_sha256(self):
        """Stored HMAC must be SHA-256 over step_id:key:value."""
        db_path = tempfile.mktemp(suffix=".db")
        env_path = tempfile.mktemp(suffix=".env")
        hmac_key = "testkey123"
        try:
            run_runner("init", db_path)
            with open(env_path, "w") as f:
                f.write("color=blue\n")
            r = run_runner("store", db_path, "step1", env_path, hmac_key)
            assert r.returncode == 0

            conn = sqlite3_mod.connect(db_path)
            row = conn.execute(
                "SELECT hmac FROM outputs WHERE step_id='step1' AND key='color'"
            ).fetchone()
            conn.close()

            stored_hmac = row[0]
            expected = hmac_mod.new(
                hmac_key.encode(), b"step1:color:blue", hashlib.sha256
            ).hexdigest()
            assert stored_hmac == expected, (
                f"HMAC must be SHA-256 over step_id:key:value, "
                f"got {stored_hmac}, expected {expected}"
            )
        finally:
            for f in [db_path, env_path]:
                if os.path.exists(f):
                    os.unlink(f)


# ── Query ─────────────────────────────────────────────────────────


class TestQuery:
    def test_query_by_key(self):
        """Query with specific key returns only that entry."""
        db_path = tempfile.mktemp(suffix=".db")
        env_path = tempfile.mktemp(suffix=".env")
        try:
            run_runner("init", db_path)
            with open(env_path, "w") as f:
                f.write("a=1\nb=2\nc=3\n")
            run_runner("store", db_path, "s1", env_path, "k")

            r = run_runner("query", db_path, "s1", "b")
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert len(data) == 1
            assert data[0] == {"key": "b", "value": "2"}
        finally:
            for f in [db_path, env_path]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_query_multiline_values(self):
        """Query must correctly return values containing newlines."""
        db_path = tempfile.mktemp(suffix=".db")
        try:
            run_runner("init", db_path)

            # Insert directly to isolate query from parser bugs
            conn = sqlite3_mod.connect(db_path)
            conn.execute(
                "INSERT INTO outputs VALUES (?, ?, ?, ?)",
                ("step1", "msg", "hello\nworld", "fake_hmac"),
            )
            conn.commit()
            conn.close()

            r = run_runner("query", db_path, "step1", "msg")
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert len(data) == 1
            assert data[0]["value"] == "hello\nworld"
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_query_empty_result(self):
        """Query for nonexistent step returns empty array."""
        db_path = tempfile.mktemp(suffix=".db")
        try:
            run_runner("init", db_path)
            r = run_runner("query", db_path, "nosuchstep")
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data == []
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ── Verify ────────────────────────────────────────────────────────


class TestVerify:
    def test_verify_valid_entries(self):
        """Verify passes when all HMACs are correct."""
        db_path = tempfile.mktemp(suffix=".db")
        env_path = tempfile.mktemp(suffix=".env")
        try:
            run_runner("init", db_path)
            with open(env_path, "w") as f:
                f.write("x=1\ny=2\n")
            run_runner("store", db_path, "s1", env_path, "mykey")

            r = run_runner("verify", db_path, "mykey")
            assert r.returncode == 0
        finally:
            for f in [db_path, env_path]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_verify_detects_tampering(self):
        """Verify fails when a stored value is tampered with."""
        db_path = tempfile.mktemp(suffix=".db")
        env_path = tempfile.mktemp(suffix=".env")
        try:
            run_runner("init", db_path)
            with open(env_path, "w") as f:
                f.write("secret=original\n")
            run_runner("store", db_path, "s1", env_path, "hmackey")

            # Tamper with the value directly
            conn = sqlite3_mod.connect(db_path)
            conn.execute(
                "UPDATE outputs SET value='tampered' WHERE key='secret'"
            )
            conn.commit()
            conn.close()

            r = run_runner("verify", db_path, "hmackey")
            assert r.returncode == 1
        finally:
            for f in [db_path, env_path]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_verify_uses_correct_hmac_algorithm(self):
        """Verify must use HMAC-SHA256 over step_id:key:value."""
        db_path = tempfile.mktemp(suffix=".db")
        hmac_key = "verifykey"
        step_id = "s1"
        key = "x"
        value = "y"
        try:
            run_runner("init", db_path)

            # Insert with independently computed correct HMAC
            correct_hmac = hmac_mod.new(
                hmac_key.encode(),
                f"{step_id}:{key}:{value}".encode(),
                hashlib.sha256,
            ).hexdigest()

            conn = sqlite3_mod.connect(db_path)
            conn.execute(
                "INSERT INTO outputs VALUES (?, ?, ?, ?)",
                (step_id, key, value, correct_hmac),
            )
            conn.commit()
            conn.close()

            r = run_runner("verify", db_path, hmac_key)
            assert r.returncode == 0, (
                f"Verify must accept correct HMAC-SHA256: {r.stderr}"
            )
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_verify_empty_db(self):
        """Verify on empty database should pass."""
        db_path = tempfile.mktemp(suffix=".db")
        try:
            run_runner("init", db_path)
            r = run_runner("verify", db_path, "anykey")
            assert r.returncode == 0
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ── Append ────────────────────────────────────────────────────────


class TestAppend:
    def test_basic_append(self):
        """Append a simple key-value pair."""
        lock_file = tempfile.mktemp(suffix=".lock")
        env_file = tempfile.mktemp(suffix=".env")
        try:
            open(env_file, "w").close()

            r = run_runner("append", lock_file, env_file, "color", "blue")
            assert r.returncode == 0

            r = run_runner("parse", env_file)
            assert r.returncode == 0
            data = json.loads(r.stdout)
            assert data == [{"key": "color", "value": "blue"}]
        finally:
            for f in [lock_file, env_file]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_append_with_single_quotes(self):
        """Values with single quotes must work in append."""
        lock_file = tempfile.mktemp(suffix=".lock")
        env_file = tempfile.mktemp(suffix=".env")
        try:
            open(env_file, "w").close()

            r = run_runner("append", lock_file, env_file, "msg", "it's working")
            # Don't check returncode — broken version hides errors with || true
            r2 = run_runner("parse", env_file)
            assert r2.returncode == 0
            data = json.loads(r2.stdout)
            assert len(data) == 1
            assert data[0] == {"key": "msg", "value": "it's working"}
        finally:
            for f in [lock_file, env_file]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_append_blocks_under_contention(self):
        """Append must block (not silently fail) when lock is contended."""
        lock_file = tempfile.mktemp(suffix=".lock")
        env_file = tempfile.mktemp(suffix=".env")
        holder = None
        try:
            open(env_file, "w").close()

            # Hold the lock externally for 0.5 seconds
            holder = subprocess.Popen(
                [
                    "bash", "-c",
                    f"exec 9>{lock_file}; flock 9; sleep 0.5; exec 9>&-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            time.sleep(0.15)  # ensure holder has the lock

            r = run_runner("append", lock_file, env_file, "waited", "yes")
            # With correct blocking flock, append waits then writes

            r2 = run_runner("parse", env_file)
            assert r2.returncode == 0
            data = json.loads(r2.stdout)
            keys = {entry["key"] for entry in data}
            assert "waited" in keys, (
                "append must block and wait for lock, not silently fail"
            )
        finally:
            if holder:
                holder.terminate()
                holder.wait()
            for f in [lock_file, env_file]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_append_multiline_eof_collision(self):
        """Append multiline value containing EOF must use safe delimiter."""
        lock_file = tempfile.mktemp(suffix=".lock")
        env_file = tempfile.mktemp(suffix=".env")
        try:
            open(env_file, "w").close()

            multiline = "start\nEOF\nend"
            r = run_runner("append", lock_file, env_file, "data", multiline)

            r2 = run_runner("parse", env_file)
            assert r2.returncode == 0
            data = json.loads(r2.stdout)
            assert len(data) == 1
            assert data[0] == {"key": "data", "value": "start\nEOF\nend"}
        finally:
            for f in [lock_file, env_file]:
                if os.path.exists(f):
                    os.unlink(f)

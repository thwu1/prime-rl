#!/usr/bin/env python3
"""Tests for shell metacharacter filter bypass audit task."""

import pytest
import json
import os
import subprocess
import importlib.util

EXPLOIT_DIR = "/app/exploits"
FIXED_SANITIZER = "/app/sanitizer_fixed.py"
ENGINE_PATH = "/app/engine.py"
SANITIZE_BINARY = "/app/bin/sanitize_direct"
ANALYSIS_DIR = "/app/analysis"

CONTEXTS = ["exec_proxy", "direct_tunnel", "checked_health"]
MARKER_FILES = {
    "exec_proxy": "/tmp/pwned_exec_proxy",
    "direct_tunnel": "/tmp/pwned_direct_tunnel",
    "checked_health": "/tmp/pwned_checked_health",
}


def load_exploit(context_name):
    """Load exploit JSON for a given context."""
    path = os.path.join(EXPLOIT_DIR, f"{context_name}.json")
    assert os.path.exists(path), f"Exploit file not found: {path}"
    with open(path) as f:
        data = json.load(f)
    assert "username" in data, "Exploit must have 'username' field"
    assert "hostname" in data, "Exploit must have 'hostname' field"
    assert "port" in data, "Exploit must have 'port' field"
    return data


def load_engine():
    """Load the engine module."""
    spec = importlib.util.spec_from_file_location("engine", ENGINE_PATH)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    return engine


def load_fixed_sanitizer():
    """Load the fixed sanitizer module."""
    assert os.path.exists(FIXED_SANITIZER), (
        f"Fixed sanitizer not found: {FIXED_SANITIZER}"
    )
    spec = importlib.util.spec_from_file_location(
        "sanitizer_fixed", FIXED_SANITIZER
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "sanitize"), (
        "Fixed sanitizer must export a 'sanitize' function"
    )
    return mod


def extract_binary_strings():
    """Extract strings from the compiled sanitizer binary."""
    result = subprocess.run(
        ["strings", SANITIZE_BINARY],
        capture_output=True,
        text=True,
    )
    return [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]


class TestExploitStructure:
    """Exploit files exist and have correct structure."""

    @pytest.mark.parametrize("context", CONTEXTS)
    def test_exploit_file_exists(self, context):
        path = os.path.join(EXPLOIT_DIR, f"{context}.json")
        assert os.path.exists(path), f"Missing exploit file: {path}"

    @pytest.mark.parametrize("context", CONTEXTS)
    def test_exploit_has_required_fields(self, context):
        exploit = load_exploit(context)
        for field in ["username", "hostname", "port"]:
            assert field in exploit, (
                f"Missing field '{field}' in {context}.json"
            )


class TestExploitsWork:
    """Each exploit achieves command execution via the vulnerable sanitizer."""

    def _run_exploit(self, context_name):
        exploit = load_exploit(context_name)
        marker = MARKER_FILES[context_name]

        if os.path.exists(marker):
            os.remove(marker)

        engine = load_engine()
        ctx = engine.CONTEXTS[context_name]
        sanitizer = ctx["sanitizer"]

        # The exploit must pass the vulnerable sanitizer
        try:
            safe_user = sanitizer(exploit["username"])
            safe_host = sanitizer(exploit["hostname"])
            safe_port = sanitizer(str(exploit["port"]))
        except ValueError as e:
            pytest.fail(
                f"Exploit for {context_name} was blocked by the vulnerable "
                f"sanitizer (it should pass through): {e}"
            )

        # Substitute into template
        cmd = ctx["template"]
        cmd = cmd.replace("%u", safe_user)
        cmd = cmd.replace("%h", safe_host)
        cmd = cmd.replace("%p", safe_port)

        if ctx["execution"] == "exec":
            full_cmd = f"exec {cmd}"
        else:
            full_cmd = cmd

        # Execute via bash
        try:
            subprocess.run(
                ["bash", "-c", full_cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            pass

        assert os.path.exists(marker), (
            f"Exploit for {context_name} did not create marker file {marker}. "
            f"The exploit payload must achieve command execution that creates "
            f"the marker file."
        )

    def test_exec_proxy_exploit(self):
        self._run_exploit("exec_proxy")

    def test_direct_tunnel_exploit(self):
        self._run_exploit("direct_tunnel")

    def test_checked_health_exploit(self):
        self._run_exploit("checked_health")


class TestBinaryAnalysis:
    """Binary analysis report files are correct."""

    def test_build_id_file_exists(self):
        assert os.path.exists(os.path.join(ANALYSIS_DIR, "build_id.txt")), (
            "Missing /app/analysis/build_id.txt"
        )

    def test_build_id_correct(self):
        """Verify build ID matches what's embedded in the binary."""
        strings_list = extract_binary_strings()
        # Find the identifier: alpha prefix, dash, hex-like suffix
        expected = None
        for s in strings_list:
            if (
                len(s) > 8
                and len(s) < 30
                and s[:4].isalpha()
                and "-" in s[4:6]
            ):
                parts = s.split("-", 1)
                if (
                    len(parts) == 2
                    and len(parts[1]) >= 8
                    and all(c.isalnum() for c in parts[1])
                ):
                    expected = s
                    break
        assert expected is not None, (
            "Could not locate build identifier in binary"
        )

        with open(os.path.join(ANALYSIS_DIR, "build_id.txt")) as f:
            user_answer = f.read().strip()
        assert user_answer == expected, (
            f"Build ID mismatch: got '{user_answer}'"
        )

    def test_blocklist_file_exists(self):
        assert os.path.exists(os.path.join(ANALYSIS_DIR, "blocklist.txt")), (
            "Missing /app/analysis/blocklist.txt"
        )

    def test_blocklist_correct(self):
        """Verify blocklist matches what's embedded in the binary."""
        strings_list = extract_binary_strings()
        # The blocklist is a string composed entirely of non-alnum, non-space chars
        expected = None
        for s in strings_list:
            if len(s) >= 10 and all(
                not c.isalnum() and not c.isspace() for c in s
            ):
                expected = s
                break
        assert expected is not None, (
            "Could not locate blocklist string in binary"
        )

        with open(os.path.join(ANALYSIS_DIR, "blocklist.txt")) as f:
            user_answer = f.read().strip()
        assert set(user_answer) == set(expected), (
            f"Blocklist character set mismatch: "
            f"expected {set(expected)}, got {set(user_answer)}"
        )


class TestFixedSanitizer:
    """The fixed sanitizer blocks all exploits and allows legitimate input."""

    def test_fixed_sanitizer_exists(self):
        assert os.path.exists(FIXED_SANITIZER)

    def test_fixed_sanitizer_has_sanitize_function(self):
        mod = load_fixed_sanitizer()
        assert callable(mod.sanitize)

    @pytest.mark.parametrize("context", CONTEXTS)
    def test_fixed_sanitizer_blocks_exploit(self, context):
        mod = load_fixed_sanitizer()
        exploit = load_exploit(context)

        blocked = False
        for field in ["username", "hostname", "port"]:
            value = str(exploit[field])
            try:
                mod.sanitize(value)
            except ValueError:
                blocked = True
                break

        assert blocked, (
            f"Fixed sanitizer must block at least one field of the "
            f"{context} exploit"
        )

    def test_allows_normal_username(self):
        mod = load_fixed_sanitizer()
        assert mod.sanitize("john.doe") == "john.doe"

    def test_allows_normal_hostname(self):
        mod = load_fixed_sanitizer()
        assert mod.sanitize("proxy.example.com") == "proxy.example.com"

    def test_allows_numeric_port(self):
        mod = load_fixed_sanitizer()
        assert mod.sanitize("8080") == "8080"

    def test_allows_email_style_user(self):
        mod = load_fixed_sanitizer()
        assert mod.sanitize("user@domain") == "user@domain"

    def test_allows_hyphenated_hostname(self):
        mod = load_fixed_sanitizer()
        result = mod.sanitize("web-proxy-01.dc1.example.com")
        assert result == "web-proxy-01.dc1.example.com"

    def test_allows_ipv4_address(self):
        mod = load_fixed_sanitizer()
        assert mod.sanitize("192.168.1.1") == "192.168.1.1"

    def test_allows_underscore(self):
        mod = load_fixed_sanitizer()
        assert mod.sanitize("my_user") == "my_user"

    def test_blocks_newline(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user\nevil")

    def test_blocks_carriage_return(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user\revil")

    def test_blocks_null_byte(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user\x00evil")

    def test_blocks_tab(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user\tevil")

    def test_blocks_dollar_bracket(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("$[+]")

    def test_blocks_semicolon(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user;evil")

    def test_blocks_backtick(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user`evil`")

    def test_blocks_pipe(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user|evil")

    def test_blocks_subshell(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("$(evil)")

    def test_blocks_space(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("user evil")

    def test_blocks_all_control_chars(self):
        mod = load_fixed_sanitizer()
        for i in list(range(0x00, 0x20)) + [0x7f]:
            with pytest.raises(ValueError, match=".*"):
                mod.sanitize(f"test{chr(i)}value")

    def test_rejects_empty_string(self):
        mod = load_fixed_sanitizer()
        with pytest.raises(ValueError):
            mod.sanitize("")

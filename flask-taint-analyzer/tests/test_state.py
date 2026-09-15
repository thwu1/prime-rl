
import json
import subprocess
import os
import tempfile
import pytest


def run_analyzer(input_path, output_path):
    """Run the taint analyzer on a Python file and return parsed results."""
    result = subprocess.run(
        ["python3", "/app/analyze.py", input_path, output_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    with open(output_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Cache main webapp analysis results so we only run the analyzer once
# ---------------------------------------------------------------------------
_main_cache = None


def _get_main():
    global _main_cache
    if _main_cache is None:
        data = run_analyzer("/app/webapp/app.py", "/tmp/main_results.json")
        findings = data["findings"]
        found_set = {(f["function"], f["cwe"]) for f in findings}
        found_funcs = {f["function"] for f in findings}
        _main_cache = (found_set, found_funcs, findings)
    return _main_cache


# ---------------------------------------------------------------------------
# Main webapp tests — true positives (8 vulnerable routes)
# ---------------------------------------------------------------------------


class TestVulnerableRoutes:
    """Each vulnerable route must be flagged with its correct CWE."""

    def test_search_sql_injection(self):
        found_set, _, _ = _get_main()
        assert ("search", "CWE-089") in found_set, (
            "Route /search: SQL injection via string concatenation must be detected"
        )

    def test_ping_command_injection(self):
        found_set, _, _ = _get_main()
        assert ("ping", "CWE-078") in found_set, (
            "Route /ping: command injection via os.popen must be detected"
        )

    def test_read_file_path_traversal(self):
        found_set, _, _ = _get_main()
        assert ("read_file", "CWE-022") in found_set, (
            "Route /read_file: path traversal via unvalidated open() must be detected"
        )

    def test_greet_xss(self):
        found_set, _, _ = _get_main()
        assert ("greet", "CWE-079") in found_set, (
            "Route /greet: XSS via render_template_string must be detected"
        )

    def test_fetch_url_ssrf(self):
        found_set, _, _ = _get_main()
        assert ("fetch_url", "CWE-918") in found_set, (
            "Route /fetch: SSRF via requests.get must be detected"
        )

    def test_users_sql_injection_through_helper(self):
        found_set, _, _ = _get_main()
        assert ("users", "CWE-089") in found_set, (
            "Route /users: SQL injection via helper function build_user_query must be detected"
        )

    def test_convert_command_injection_subprocess_shell(self):
        found_set, _, _ = _get_main()
        assert ("convert", "CWE-078") in found_set, (
            "Route /convert: command injection via subprocess.call(shell=True) must be detected"
        )

    def test_doc_path_traversal_through_class_method(self):
        found_set, _, _ = _get_main()
        assert ("doc", "CWE-022") in found_set, (
            "Route /doc: path traversal via FileManager.get_content must be detected"
        )


# ---------------------------------------------------------------------------
# Main webapp tests — true negatives (4 safe routes)
# ---------------------------------------------------------------------------


class TestSafeRoutes:
    """Properly sanitized routes must NOT appear in findings."""

    def test_search_safe_not_flagged(self):
        _, found_funcs, _ = _get_main()
        assert "search_safe" not in found_funcs, (
            "Route /search_safe uses parameterized query and must not be flagged"
        )

    def test_ping_safe_not_flagged(self):
        _, found_funcs, _ = _get_main()
        assert "ping_safe" not in found_funcs, (
            "Route /ping_safe uses subprocess with list args and must not be flagged"
        )

    def test_read_file_safe_not_flagged(self):
        _, found_funcs, _ = _get_main()
        assert "read_file_safe" not in found_funcs, (
            "Route /read_file_safe uses realpath+startswith and must not be flagged"
        )

    def test_lookup_not_flagged(self):
        _, found_funcs, _ = _get_main()
        assert "lookup" not in found_funcs, (
            "Route /lookup validates input chars and must not be flagged"
        )


# ---------------------------------------------------------------------------
# Output format validation
# ---------------------------------------------------------------------------


class TestOutputFormat:
    """Verify the JSON schema of the analyzer output."""

    def test_findings_key_exists(self):
        _, _, findings = _get_main()
        assert isinstance(findings, list)

    def test_each_finding_has_required_fields(self):
        _, _, findings = _get_main()
        for f in findings:
            assert "cwe" in f, f"Finding missing 'cwe': {f}"
            assert "function" in f, f"Finding missing 'function': {f}"
            assert "sink_type" in f, f"Finding missing 'sink_type': {f}"

    def test_cwe_format(self):
        _, _, findings = _get_main()
        for f in findings:
            assert f["cwe"].startswith("CWE-"), f"CWE must start with 'CWE-': {f}"

    def test_sink_types_valid(self):
        valid = {"sql_injection", "command_injection", "path_traversal", "xss", "ssrf"}
        _, _, findings = _get_main()
        for f in findings:
            assert f["sink_type"] in valid, (
                f"Invalid sink_type '{f['sink_type']}'; must be one of {valid}"
            )


# ---------------------------------------------------------------------------
# Additional test cases — prevent hardcoded results
# ---------------------------------------------------------------------------


def _run_on_code(code):
    """Write code to a temp file, run the analyzer, return found function names."""
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, dir="/tmp"
    ) as f:
        f.write(code)
        in_path = f.name
    out_path = in_path + ".json"
    try:
        data = run_analyzer(in_path, out_path)
        return {entry["function"] for entry in data["findings"]}
    finally:
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


class TestAdditionalSQLInjection:
    """Analyzer must generalise beyond the main webapp."""

    def test_detects_concat_sqli(self):
        code = (
            "from flask import Flask, request\n"
            "import sqlite3\n"
            "app = Flask(__name__)\n"
            "@app.route('/t')\n"
            "def vuln():\n"
            "    v = request.args.get('x')\n"
            "    c = sqlite3.connect(':memory:')\n"
            "    c.execute(\"SELECT * FROM t WHERE a = '\" + v + \"'\")\n"
            "    return 'ok'\n"
            "@app.route('/s')\n"
            "def safe():\n"
            "    v = request.args.get('x')\n"
            "    c = sqlite3.connect(':memory:')\n"
            "    c.execute('SELECT * FROM t WHERE a = ?', (v,))\n"
            "    return 'ok'\n"
        )
        found = _run_on_code(code)
        assert "vuln" in found, "Must detect SQL injection via string concat"
        assert "safe" not in found, "Must not flag parameterized query"


class TestAdditionalCommandInjection:
    def test_detects_os_system(self):
        code = (
            "from flask import Flask, request\n"
            "import os, subprocess\n"
            "app = Flask(__name__)\n"
            "@app.route('/t')\n"
            "def vuln():\n"
            "    h = request.args.get('h')\n"
            "    os.system('ping ' + h)\n"
            "    return 'ok'\n"
            "@app.route('/s')\n"
            "def safe():\n"
            "    h = request.args.get('h')\n"
            "    subprocess.run(['ping', '-c', '1', h])\n"
            "    return 'ok'\n"
        )
        found = _run_on_code(code)
        assert "vuln" in found, "Must detect command injection via os.system"
        assert "safe" not in found, "Must not flag subprocess with list args"


class TestAdditionalPathTraversal:
    def test_detects_open_concat(self):
        code = (
            "from flask import Flask, request\n"
            "import os\n"
            "app = Flask(__name__)\n"
            "@app.route('/t')\n"
            "def vuln():\n"
            "    n = request.args.get('n')\n"
            "    f = open('/data/' + n)\n"
            "    return f.read()\n"
            "@app.route('/s')\n"
            "def safe():\n"
            "    n = request.args.get('n')\n"
            "    p = os.path.realpath(os.path.join('/data', n))\n"
            "    if not p.startswith('/data'):\n"
            "        return 'no'\n"
            "    f = open(p)\n"
            "    return f.read()\n"
        )
        found = _run_on_code(code)
        assert "vuln" in found, "Must detect path traversal via open(concat)"
        assert "safe" not in found, "Must not flag path with realpath+startswith"

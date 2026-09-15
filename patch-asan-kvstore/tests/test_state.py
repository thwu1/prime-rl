
"""
Verify that:
1. The peer audit review correctly identifies errors in the prior analyst's work
2. All memory-safety vulnerabilities are fixed and the binary passes ASan
3. A corrected security audit with exploitability assessments exists
4. Valid inputs produce correct output
"""

import json
import os
import re
import subprocess
import tempfile

import pytest

KVSTORE = "/app/kvstore"


def run_kvstore(input_data, timeout=10):
    """Run kvstore on an inline command string, return (stdout, stderr, rc)."""
    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "detect_leaks=0"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
        f.write(input_data)
        tmpname = f.name
    try:
        result = subprocess.run(
            [KVSTORE, tmpname],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    finally:
        os.unlink(tmpname)
    return result.stdout, result.stderr, result.returncode


def run_kvstore_file(input_file, timeout=10):
    """Run kvstore on a pre-existing file."""
    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "detect_leaks=0"
    result = subprocess.run(
        [KVSTORE, input_file],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.stdout, result.stderr, result.returncode


# ------------------------------------------------------------------ #
#  Peer review evaluation tests                                       #
# ------------------------------------------------------------------ #

class TestPeerReview:
    """The peer review must correctly identify errors in the prior audit."""

    REVIEW_PATH = "/app/peer_review.json"

    def _load(self):
        with open(self.REVIEW_PATH) as f:
            return json.load(f)

    def _find_review_by_id(self, reviews, target_id):
        """Find a review entry matching a peer audit ID."""
        for r in reviews:
            rid = r.get("peer_audit_id", r.get("id", None))
            if rid == target_id:
                return r
        return None

    def _find_review_by_keyword(self, reviews, keyword):
        """Fallback: find review mentioning a keyword."""
        for r in reviews:
            text = json.dumps(r).lower()
            if keyword.lower() in text:
                return r
        return None

    def _get_review(self, data, entry_id, keyword):
        """Get review by ID first, then keyword fallback."""
        reviews = data.get("reviews", [])
        r = self._find_review_by_id(reviews, entry_id)
        if r is None:
            r = self._find_review_by_keyword(reviews, keyword)
        return r

    def test_file_exists(self):
        assert os.path.isfile(self.REVIEW_PATH), (
            f"Peer review not found at {self.REVIEW_PATH}"
        )

    def test_valid_structure(self):
        data = self._load()
        assert "reviews" in data, "Peer review must have a 'reviews' key"
        assert isinstance(data["reviews"], list)
        assert len(data["reviews"]) >= 4, (
            f"Must review all 4 peer audit entries, found {len(data['reviews'])}"
        )

    def test_entry1_severity_flagged(self):
        """Peer audit entry 1 rates parse_quoted heap overflow as 'low' — must be flagged."""
        data = self._load()
        review = self._get_review(data, 1, "parse_quoted")
        assert review is not None, "No review found for peer audit entry 1 (parse_quoted)"
        verdict = str(review.get("verdict", "")).lower().strip()
        assert verdict != "correct", (
            "Entry 1 (parse_quoted severity='low' for heap overflow) should not be 'correct' — "
            "heap buffer overflow enabling metadata corruption warrants at least 'high' severity"
        )

    def test_entry2_root_cause_misattribution(self):
        """Peer audit entry 2 attributes UAF to cmd_get — must identify cmd_rename as root cause."""
        data = self._load()
        review = self._get_review(data, 2, "cmd_get")
        assert review is not None, "No review found for peer audit entry 2 (cmd_get)"

        verdict = str(review.get("verdict", "")).lower().strip()
        assert verdict != "correct", (
            "Entry 2 (root cause attributed to cmd_get) must be flagged — "
            "cmd_get is the crash site, not the root cause"
        )

        # Must identify cmd_rename as the actual root cause
        text = json.dumps(review).lower()
        assert "rename" in text, (
            "Review of entry 2 must identify cmd_rename as the actual root cause function. "
            f"Review content: {json.dumps(review)[:300]}"
        )

    def test_entry3_accepted(self):
        """Peer audit entry 3 (cmd_keys stack overflow) is correct — should not be 'incorrect'."""
        data = self._load()
        review = self._get_review(data, 3, "cmd_keys")
        assert review is not None, "No review found for peer audit entry 3 (cmd_keys)"
        verdict = str(review.get("verdict", "")).lower().strip()
        assert verdict != "incorrect", (
            "Entry 3 (cmd_keys CWE-121 stack overflow) is correctly identified — "
            "should be 'correct' or 'partially_correct', not 'incorrect'"
        )

    def test_entry4_cwe_error_identified(self):
        """Peer audit entry 4 uses CWE-787 (write) — must identify it as a read vulnerability."""
        data = self._load()
        review = self._get_review(data, 4, "getrange")
        assert review is not None, "No review found for peer audit entry 4 (cmd_getrange)"

        verdict = str(review.get("verdict", "")).lower().strip()
        assert verdict != "correct", (
            "Entry 4 (CWE-787 for OOB read in getrange) must be flagged — "
            "CWE-787 is out-of-bounds write, but the bug is an out-of-bounds read"
        )

        text = json.dumps(review).lower()
        assert any(x in text for x in ["125", "126", "read", "over-read"]), (
            "Review of entry 4 must identify the bug as a read (CWE-125/126), "
            f"not a write (CWE-787). Review content: {json.dumps(review)[:300]}"
        )

    def test_missing_vulnerabilities_identified(self):
        """Must identify cmd_copy and cmd_mget as missing from the peer audit."""
        data = self._load()
        all_text = json.dumps(data).lower()
        assert "copy" in all_text, (
            "Must identify cmd_copy self-copy UAF as missing from the peer audit"
        )
        assert "mget" in all_text, (
            "Must identify cmd_mget stack buffer overflow as missing from the peer audit"
        )


# ------------------------------------------------------------------ #
#  PoC regression tests – ASan-reported vulnerabilities               #
# ------------------------------------------------------------------ #

class TestPoCFixed:
    """Each ASan-reported PoC must no longer crash after patching."""

    @pytest.mark.parametrize("poc_num,vuln_class", [
        (1, "heap-buffer-overflow (write) in parse_quoted"),
        (2, "heap-use-after-free in cmd_rename / cmd_get"),
        (3, "stack-buffer-overflow in cmd_keys"),
        (4, "heap-buffer-overflow (read) in cmd_getrange"),
    ])
    def test_poc_no_crash(self, poc_num, vuln_class):
        poc_file = f"/app/poc/poc{poc_num}.cfg"
        stdout, stderr, rc = run_kvstore_file(poc_file)
        assert rc == 0, (
            f"PoC {poc_num} ({vuln_class}) still crashes (rc={rc}).\n"
            f"stderr (first 800 chars):\n{stderr[:800]}"
        )
        assert "AddressSanitizer" not in stderr, (
            f"PoC {poc_num} ({vuln_class}) still triggers ASan.\n"
            f"stderr (first 800 chars):\n{stderr[:800]}"
        )


# ------------------------------------------------------------------ #
#  Hidden vulnerability tests – no ASan reports provided              #
# ------------------------------------------------------------------ #

class TestHiddenVulnerabilities:
    """Vulnerabilities not covered by the provided ASan reports."""

    def test_copy_self_no_crash(self):
        """COPY key key (self-copy) must not trigger use-after-free."""
        input_data = (
            "SET selfkey important_data_value\n"
            "COPY selfkey selfkey\n"
            "GET selfkey\n"
            "QUIT\n"
        )
        stdout, stderr, rc = run_kvstore(input_data)
        assert rc == 0, (
            f"COPY self-copy crashed (rc={rc})\nstderr: {stderr[:800]}"
        )
        assert "AddressSanitizer" not in stderr, (
            f"COPY self-copy triggers ASan\nstderr: {stderr[:800]}"
        )
        lines = [l for l in stdout.strip().split("\n") if l]
        assert "important_data_value" in lines[-1], (
            f"Value corrupted after self-copy. "
            f"Expected 'important_data_value' in last line, got: {lines[-1]}"
        )

    def test_copy_self_repeated(self):
        """Repeated self-copy must preserve data integrity."""
        input_data = (
            "SET alpha test_string_12345\n"
            "COPY alpha alpha\n"
            "COPY alpha alpha\n"
            "COPY alpha alpha\n"
            "GET alpha\n"
            "STRLEN alpha\n"
            "QUIT\n"
        )
        stdout, stderr, rc = run_kvstore(input_data)
        assert rc == 0, f"Repeated self-copy crashed\nstderr: {stderr[:800]}"
        assert "AddressSanitizer" not in stderr
        assert "test_string_12345" in stdout
        assert "(17)" in stdout  # len("test_string_12345") == 17

    def test_mget_large_values_no_overflow(self):
        """MGET with many large values must not overflow stack buffer."""
        cmds = []
        for i in range(8):
            val = chr(ord("A") + i) * 100
            cmds.append(f"SET key{i} {val}")
        cmds.append("MGET " + " ".join(f"key{i}" for i in range(8)))
        cmds.append("QUIT")
        input_data = "\n".join(cmds) + "\n"

        stdout, stderr, rc = run_kvstore(input_data)
        assert rc == 0, (
            f"MGET large values crashed (rc={rc})\nstderr: {stderr[:800]}"
        )
        assert "AddressSanitizer" not in stderr, (
            f"MGET large values triggers ASan\nstderr: {stderr[:800]}"
        )

    def test_mget_overflow_boundary(self):
        """MGET output exceeding MGET_BUF (512) bytes must not corrupt stack."""
        cmds = []
        for i in range(6):
            val = f"val{'X' * 118}{i}"
            cmds.append(f"SET longkey{i} {val}")
        cmds.append("MGET " + " ".join(f"longkey{i}" for i in range(6)))
        cmds.append("QUIT")
        input_data = "\n".join(cmds) + "\n"

        stdout, stderr, rc = run_kvstore(input_data)
        assert rc == 0, (
            f"MGET boundary test crashed (rc={rc})\nstderr: {stderr[:800]}"
        )
        assert "AddressSanitizer" not in stderr
        for i in range(6):
            assert f"{i+1})" in stdout, (
                f"Missing MGET entry {i+1} in output"
            )

    def test_mget_correct_output(self):
        """MGET must produce correctly formatted output for valid inputs."""
        input_data = "SET a hello\nSET b world\nMGET a b c\nQUIT\n"
        stdout, stderr, rc = run_kvstore(input_data)
        assert rc == 0
        assert "AddressSanitizer" not in stderr
        assert "1) hello" in stdout
        assert "2) world" in stdout
        assert "3) (nil)" in stdout


# ------------------------------------------------------------------ #
#  Functional tests – correct output on valid inputs                  #
# ------------------------------------------------------------------ #

class TestValidOutputs:
    """Valid command sequences must produce the expected output."""

    @pytest.mark.parametrize("test_num,description", [
        (1, "SET/GET/DEL/COPY/APPEND/EXISTS/STRLEN"),
        (2, "RENAME and GETRANGE"),
        (3, "KEYS pattern matching and DUMP"),
        (4, "MGET basic functionality"),
    ])
    def test_valid_output(self, test_num, description):
        valid_file = f"/app/tests/valid/valid{test_num}.cfg"
        expected_file = f"/app/tests/expected/expected{test_num}.txt"

        stdout, stderr, rc = run_kvstore_file(valid_file)
        assert rc == 0, (
            f"Valid test {test_num} ({description}) crashed (rc={rc}).\n"
            f"stderr: {stderr[:500]}"
        )
        assert "AddressSanitizer" not in stderr, (
            f"Valid test {test_num} triggered ASan.\nstderr: {stderr[:500]}"
        )

        with open(expected_file) as f:
            expected = f.read().strip()

        assert stdout.strip() == expected, (
            f"Output mismatch for valid test {test_num} ({description}).\n"
            f"--- Expected ---\n{expected}\n"
            f"--- Got ---\n{stdout.strip()}"
        )


# ------------------------------------------------------------------ #
#  Security audit report validation                                   #
# ------------------------------------------------------------------ #

class TestSecurityAudit:
    """Corrected security audit must be accurate and complete."""

    AUDIT_PATH = "/app/security_audit.json"

    # Mapping: canonical function name -> set of acceptable CWE IDs
    EXPECTED_VULNS = {
        "parse_quoted": {"CWE-122", "CWE-787", "CWE-131"},
        "cmd_rename":   {"CWE-416"},
        "cmd_keys":     {"CWE-121", "CWE-787", "CWE-120"},
        "cmd_getrange": {"CWE-125", "CWE-126"},
        "cmd_copy":     {"CWE-416"},
        "cmd_mget":     {"CWE-121", "CWE-787", "CWE-120"},
    }

    VALID_SEVERITIES = {"critical", "high", "medium", "low"}
    VALID_EXPLOITABILITY = {"code_execution", "info_disclosure", "dos_only"}

    @staticmethod
    def _normalize_cwe(raw):
        """Extract CWE-NNN from various user formats."""
        m = re.search(r"(\d+)", str(raw))
        if m:
            return f"CWE-{m.group(1)}"
        return ""

    @staticmethod
    def _matches_function(audit_func, canonical):
        """Flexible match: 'cmd_rename', 'rename', 'cmd_rename()' all match."""
        a = audit_func.lower().strip()
        c = canonical.lower()
        if c in a:
            return True
        short = c.replace("cmd_", "")
        if len(short) > 3 and short in a:
            return True
        return False

    def _load_audit(self):
        with open(self.AUDIT_PATH) as f:
            return json.load(f)

    def test_audit_file_exists(self):
        assert os.path.isfile(self.AUDIT_PATH), (
            f"Security audit report not found at {self.AUDIT_PATH}"
        )

    def test_audit_valid_json(self):
        data = self._load_audit()
        assert "vulnerabilities" in data, (
            "Audit JSON must contain a 'vulnerabilities' key"
        )
        assert isinstance(data["vulnerabilities"], list)

    def test_audit_minimum_count(self):
        data = self._load_audit()
        vulns = data["vulnerabilities"]
        assert len(vulns) >= 6, (
            f"Audit has {len(vulns)} entries, expected at least 6 "
            f"(4 ASan-reported + 2 discovered through code review)"
        )

    def test_audit_entry_structure(self):
        data = self._load_audit()
        required = {"cwe_id", "function", "severity", "description",
                     "fix_description", "exploitability"}
        for i, vuln in enumerate(data["vulnerabilities"]):
            missing = required - set(vuln.keys())
            assert not missing, f"Audit entry {i} missing fields: {missing}"
            for field in required:
                assert vuln[field], f"Audit entry {i} has empty '{field}'"

    def test_audit_function_coverage(self):
        """All vulnerable functions must be identified in the audit."""
        data = self._load_audit()
        vulns = data["vulnerabilities"]
        for canonical in self.EXPECTED_VULNS:
            found = any(
                self._matches_function(v.get("function", ""), canonical)
                for v in vulns
            )
            assert found, (
                f"Vulnerability in '{canonical}' not documented in audit. "
                f"Found functions: {sorted(set(v.get('function','') for v in vulns))}"
            )

    def test_audit_cwe_accuracy(self):
        """CWE IDs must be correct for each identified vulnerable function."""
        data = self._load_audit()
        for vuln in data["vulnerabilities"]:
            func_field = vuln.get("function", "")
            cwe_norm = self._normalize_cwe(vuln.get("cwe_id", ""))
            for canonical, acceptable in self.EXPECTED_VULNS.items():
                if self._matches_function(func_field, canonical):
                    assert cwe_norm in acceptable, (
                        f"Incorrect CWE for '{func_field}' "
                        f"(matched '{canonical}'): got {cwe_norm}, "
                        f"expected one of {sorted(acceptable)}"
                    )
                    break

    def test_audit_severity_valid(self):
        """All severity ratings must use valid values."""
        data = self._load_audit()
        for vuln in data["vulnerabilities"]:
            sev = vuln.get("severity", "").lower().strip()
            assert sev in self.VALID_SEVERITIES, (
                f"Invalid severity '{sev}' for "
                f"{vuln.get('function', '?')}: "
                f"must be one of {sorted(self.VALID_SEVERITIES)}"
            )

    def test_exploitability_present(self):
        """Each vulnerability must have a valid exploitability assessment."""
        data = self._load_audit()
        for i, vuln in enumerate(data["vulnerabilities"]):
            assert "exploitability" in vuln, (
                f"Audit entry {i} ({vuln.get('function', '?')}) missing 'exploitability'"
            )
            exp = vuln["exploitability"].lower().strip()
            assert exp in self.VALID_EXPLOITABILITY, (
                f"Audit entry {i} ({vuln.get('function', '?')}) has invalid "
                f"exploitability '{exp}', must be one of {sorted(self.VALID_EXPLOITABILITY)}"
            )

    def test_exploitability_getrange_is_disclosure(self):
        """cmd_getrange is an OOB read — exploitability must be info_disclosure."""
        data = self._load_audit()
        for vuln in data["vulnerabilities"]:
            if self._matches_function(vuln.get("function", ""), "cmd_getrange"):
                exp = vuln.get("exploitability", "").lower().strip()
                assert exp == "info_disclosure", (
                    f"cmd_getrange is a read-only out-of-bounds vulnerability — "
                    f"exploitability should be 'info_disclosure', got '{exp}'. "
                    f"OOB reads leak adjacent heap data but cannot directly "
                    f"enable code execution."
                )

    def test_exploitability_uaf_not_dos_only(self):
        """Use-after-free vulnerabilities are code execution primitives, not merely DoS."""
        data = self._load_audit()
        uaf_funcs = ["cmd_rename", "cmd_copy"]
        for vuln in data["vulnerabilities"]:
            for uf in uaf_funcs:
                if self._matches_function(vuln.get("function", ""), uf):
                    exp = vuln.get("exploitability", "").lower().strip()
                    assert exp != "dos_only", (
                        f"{vuln.get('function')} is a use-after-free — "
                        f"exploitability should not be 'dos_only'. "
                        f"UAF enables heap manipulation for code execution."
                    )

    def test_exploitability_overflow_not_dos_only(self):
        """Buffer overflow write vulnerabilities enable code execution."""
        data = self._load_audit()
        overflow_funcs = ["parse_quoted", "cmd_keys", "cmd_mget"]
        for vuln in data["vulnerabilities"]:
            for of in overflow_funcs:
                if self._matches_function(vuln.get("function", ""), of):
                    exp = vuln.get("exploitability", "").lower().strip()
                    assert exp != "dos_only", (
                        f"{vuln.get('function')} is a buffer overflow write — "
                        f"exploitability should not be 'dos_only'. "
                        f"Heap/stack overflow writes can corrupt control flow."
                    )

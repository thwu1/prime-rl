
"""Tests for COBOL DAILYPOST migration.

All expected values are derived dynamically by compiling and running
the COBOL program with GnuCOBOL at test time. No hardcoded expected
balances, hashes, or record contents exist in this file.
"""

import hashlib
import os
import re
import pytest


REF_DIR = "/tmp/cobol_ref/output"
AGENT_DIR = "/app/output"

ACCT_LEN = 72
EXC_LEN = 88
SUMM_LEN = 80


# ── COMP-3 decode utility ────────────────────────────────────────────

def unpack_comp3(data: bytes) -> int:
    """Decode COMP-3 packed decimal bytes to integer."""
    nibbles = []
    for b in data:
        nibbles.append((b >> 4) & 0xF)
        nibbles.append(b & 0xF)
    sign = nibbles.pop()
    neg = sign == 0xD
    value = int("".join(str(n) for n in nibbles))
    return -value if neg else value


def parse_account(data: bytes, offset: int = 0) -> dict:
    r = data[offset:offset + ACCT_LEN]
    return {
        "acct_id": r[0:10].decode("ascii").strip(),
        "curr_bal": unpack_comp3(r[33:40]),
        "last_activity": r[58:66].decode("ascii"),
    }


def parse_exception(data: bytes, offset: int = 0) -> dict:
    r = data[offset:offset + EXC_LEN]
    return {
        "txn_acct_id": r[0:10].decode("ascii").strip(),
        "txn_id": r[10:22].decode("ascii").strip(),
        "reason_cd": r[64:68].decode("ascii"),
    }


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ── Anti-cheat: source code analysis ─────────────────────────────────

class TestAntiCheat:
    """Verify posting.py is a genuine Python reimplementation, not a
    wrapper around the COBOL compiler or pre-computed output."""

    @pytest.fixture(autouse=True)
    def load_source(self):
        with open("/app/posting.py", "r") as f:
            self.source = f.read()
        self.source_lower = self.source.lower()

    def test_no_subprocess_module(self):
        assert "subprocess" not in self.source, \
            "posting.py must not use the subprocess module"

    def test_no_os_system_calls(self):
        assert "os.system" not in self.source, \
            "posting.py must not call os.system()"

    def test_no_os_popen_calls(self):
        assert "os.popen" not in self.source, \
            "posting.py must not call os.popen()"

    def test_no_popen_direct(self):
        assert "Popen" not in self.source, \
            "posting.py must not use Popen"

    def test_no_os_exec_family(self):
        assert not re.search(r'os\.exec[a-z]+', self.source), \
            "posting.py must not use os.exec* functions"

    def test_no_compiler_reference(self):
        assert "cobc" not in self.source_lower, \
            "posting.py must not reference the cobc compiler"
        assert "gnucobol" not in self.source_lower, \
            "posting.py must not reference gnucobol"

    def test_no_dynamic_code_execution(self):
        assert not re.search(r'\beval\s*\(', self.source), \
            "posting.py must not use eval()"
        assert not re.search(r'(?<![a-zA-Z])exec\s*\(', self.source), \
            "posting.py must not use exec()"

    def test_no_dunder_import(self):
        assert "__import__" not in self.source, \
            "posting.py must not use __import__()"

    def test_contains_computation_logic(self):
        """A genuine reimplementation must contain packed decimal handling
        and arithmetic computation logic."""
        indicators = [
            "Decimal", "ROUND_HALF_UP", "quantize",
            "struct.unpack", "int.from_bytes",
            "pack", "nibble",
            "0xC", "0xD", "0xF",
        ]
        found = sum(1 for ind in indicators if ind in self.source)
        assert found >= 3, \
            (f"posting.py contains only {found}/10 expected computation "
             f"indicators — a genuine reimplementation needs >= 3")

    def test_minimum_code_size(self):
        """A genuine reimplementation requires substantial code."""
        lines = [l for l in self.source.splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        assert len(lines) >= 50, \
            (f"posting.py has only {len(lines)} non-empty non-comment "
             f"lines — expected >= 50 for a genuine reimplementation")


# ── Reference sanity checks ──────────────────────────────────────────

class TestReferenceGenerated:
    """Ensure the COBOL reference was compiled and run successfully."""

    def test_ref_accounts_exist(self):
        assert os.path.exists(f"{REF_DIR}/accounts_out.dat"), \
            "COBOL reference accounts_out.dat not generated"

    def test_ref_exceptions_exist(self):
        assert os.path.exists(f"{REF_DIR}/exceptions.dat"), \
            "COBOL reference exceptions.dat not generated"

    def test_ref_summary_exist(self):
        assert os.path.exists(f"{REF_DIR}/summary.dat"), \
            "COBOL reference summary.dat not generated"


# ── Agent output existence ────────────────────────────────────────────

class TestOutputFilesExist:

    def test_posting_py_exists(self):
        assert os.path.exists("/app/posting.py"), \
            "Missing /app/posting.py"

    def test_accounts_out_exists(self):
        assert os.path.exists(f"{AGENT_DIR}/accounts_out.dat"), \
            f"Missing {AGENT_DIR}/accounts_out.dat"

    def test_exceptions_exists(self):
        assert os.path.exists(f"{AGENT_DIR}/exceptions.dat"), \
            f"Missing {AGENT_DIR}/exceptions.dat"

    def test_summary_exists(self):
        assert os.path.exists(f"{AGENT_DIR}/summary.dat"), \
            f"Missing {AGENT_DIR}/summary.dat"


# ── File size checks ──────────────────────────────────────────────────

class TestOutputFileSizes:

    def test_accounts_size_matches(self):
        agent_size = os.path.getsize(f"{AGENT_DIR}/accounts_out.dat")
        ref_size = os.path.getsize(f"{REF_DIR}/accounts_out.dat")
        assert agent_size == ref_size, \
            f"accounts_out.dat: {agent_size} bytes (expected {ref_size})"

    def test_exceptions_size_matches(self):
        agent_size = os.path.getsize(f"{AGENT_DIR}/exceptions.dat")
        ref_size = os.path.getsize(f"{REF_DIR}/exceptions.dat")
        assert agent_size == ref_size, \
            f"exceptions.dat: {agent_size} bytes (expected {ref_size})"

    def test_summary_size(self):
        agent_size = os.path.getsize(f"{AGENT_DIR}/summary.dat")
        ref_size = os.path.getsize(f"{REF_DIR}/summary.dat")
        assert agent_size == ref_size, \
            f"summary.dat: {agent_size} bytes (expected {ref_size})"


# ── Byte-identical comparison (final gate) ────────────────────────────

class TestByteIdentical:
    """SHA-256 must match the COBOL reference byte-for-byte."""

    def test_accounts_sha256(self):
        actual = sha256(f"{AGENT_DIR}/accounts_out.dat")
        expected = sha256(f"{REF_DIR}/accounts_out.dat")
        assert actual == expected, \
            f"accounts_out.dat SHA-256 mismatch:\n  actual:   {actual}\n  expected: {expected}"

    def test_exceptions_sha256(self):
        actual = sha256(f"{AGENT_DIR}/exceptions.dat")
        expected = sha256(f"{REF_DIR}/exceptions.dat")
        assert actual == expected, \
            f"exceptions.dat SHA-256 mismatch:\n  actual:   {actual}\n  expected: {expected}"

    def test_summary_sha256(self):
        actual = sha256(f"{AGENT_DIR}/summary.dat")
        expected = sha256(f"{REF_DIR}/summary.dat")
        assert actual == expected, \
            f"summary.dat SHA-256 mismatch:\n  actual:   {actual}\n  expected: {expected}"


# ── Diagnostic: per-account comparison ────────────────────────────────

class TestAccountDetails:
    """Compare individual account fields for detailed diagnostics."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.agent_data = open(f"{AGENT_DIR}/accounts_out.dat", "rb").read()
        self.ref_data = open(f"{REF_DIR}/accounts_out.dat", "rb").read()

    def test_all_account_balances(self):
        n = len(self.ref_data) // ACCT_LEN
        for idx in range(n):
            ref = parse_account(self.ref_data, idx * ACCT_LEN)
            agent = parse_account(self.agent_data, idx * ACCT_LEN)
            assert agent["curr_bal"] == ref["curr_bal"], \
                (f"Account {ref['acct_id']}: "
                 f"balance {agent['curr_bal']} "
                 f"(${agent['curr_bal'] / 100:.2f}) != "
                 f"expected {ref['curr_bal']} "
                 f"(${ref['curr_bal'] / 100:.2f})")

    def test_all_account_last_activity(self):
        n = len(self.ref_data) // ACCT_LEN
        for idx in range(n):
            ref = parse_account(self.ref_data, idx * ACCT_LEN)
            agent = parse_account(self.agent_data, idx * ACCT_LEN)
            assert agent["last_activity"] == ref["last_activity"], \
                (f"Account {ref['acct_id']}: "
                 f"last_activity {agent['last_activity']} != "
                 f"{ref['last_activity']}")


# ── Diagnostic: exception comparison ──────────────────────────────────

class TestExceptionDetails:
    """Compare exception records for diagnostics."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.agent_data = open(f"{AGENT_DIR}/exceptions.dat", "rb").read()
        self.ref_data = open(f"{REF_DIR}/exceptions.dat", "rb").read()

    def test_exception_count(self):
        agent_n = len(self.agent_data) // EXC_LEN
        ref_n = len(self.ref_data) // EXC_LEN
        assert agent_n == ref_n, \
            f"Exception count: {agent_n} != expected {ref_n}"

    def test_all_exception_records(self):
        n = len(self.ref_data) // EXC_LEN
        for idx in range(n):
            ref = parse_exception(self.ref_data, idx * EXC_LEN)
            agent = parse_exception(self.agent_data, idx * EXC_LEN)
            assert agent["txn_acct_id"] == ref["txn_acct_id"], \
                f"Exception {idx}: acct {agent['txn_acct_id']} != {ref['txn_acct_id']}"
            assert agent["reason_cd"] == ref["reason_cd"], \
                f"Exception {idx}: code {agent['reason_cd']} != {ref['reason_cd']}"


# ── Diagnostic: summary comparison ────────────────────────────────────

class TestSummaryDetails:
    """Compare summary control totals."""

    @pytest.fixture(autouse=True)
    def load_data(self):
        self.agent_data = open(f"{AGENT_DIR}/summary.dat", "rb").read()
        self.ref_data = open(f"{REF_DIR}/summary.dat", "rb").read()

    def test_summary_label(self):
        assert self.agent_data[0:4] == self.ref_data[0:4], \
            f"Summary label: {self.agent_data[0:4]} != {self.ref_data[0:4]}"

    def test_summary_debits(self):
        agent_val = unpack_comp3(self.agent_data[4:11])
        ref_val = unpack_comp3(self.ref_data[4:11])
        assert agent_val == ref_val, \
            f"Summary total debits: {agent_val} != {ref_val}"

    def test_summary_credits(self):
        agent_val = unpack_comp3(self.agent_data[11:18])
        ref_val = unpack_comp3(self.ref_data[11:18])
        assert agent_val == ref_val, \
            f"Summary total credits: {agent_val} != {ref_val}"

    def test_summary_acct_count(self):
        agent_val = unpack_comp3(self.agent_data[18:22])
        ref_val = unpack_comp3(self.ref_data[18:22])
        assert agent_val == ref_val, \
            f"Summary account count: {agent_val} != {ref_val}"

    def test_summary_exc_count(self):
        agent_val = unpack_comp3(self.agent_data[22:26])
        ref_val = unpack_comp3(self.ref_data[22:26])
        assert agent_val == ref_val, \
            f"Summary exception count: {agent_val} != {ref_val}"

    def test_summary_txn_count(self):
        agent_val = unpack_comp3(self.agent_data[26:30])
        ref_val = unpack_comp3(self.ref_data[26:30])
        assert agent_val == ref_val, \
            f"Summary txn applied count: {agent_val} != {ref_val}"

    def test_summary_hash_total(self):
        agent_val = unpack_comp3(self.agent_data[30:38])
        ref_val = unpack_comp3(self.ref_data[30:38])
        assert agent_val == ref_val, \
            f"Summary hash total: {agent_val} != {ref_val}"

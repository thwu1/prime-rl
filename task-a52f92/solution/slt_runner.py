#!/usr/bin/env python3
"""
sqllogictest-compatible parser and runner for SQLite.

"""

import sqlite3
import re
import json
import hashlib
import subprocess
import sys
import os
import glob as globmod
import time
import argparse
import tempfile
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any, Dict


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Record:
    """A parsed SLT record."""
    type: str
    line: int
    sql: str = ""
    command: str = ""
    expect: str = "ok"
    types: str = ""
    sort_mode: Optional[str] = None  # None means "use default"
    label: Optional[str] = None
    expected_results: Optional[List[str]] = None
    error_pattern: Optional[str] = None
    multiline_error: Optional[str] = None
    expected_count: Optional[int] = None
    expected_stdout: Optional[str] = None
    retry_attempts: Optional[int] = None
    retry_backoff: Optional[str] = None
    conditions: List[Tuple[str, str]] = field(default_factory=list)
    variables: List[str] = field(default_factory=list)
    setting: str = ""
    value: str = ""
    pattern: str = ""
    base_dir: str = ""
    threshold: int = 0
    name: str = ""
    duration: str = ""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def parse_duration(s: str) -> float:
    """Parse duration string (e.g. '1s', '500ms', '2m30s') into seconds."""
    total = 0.0
    s = s.strip()
    for m in re.finditer(r"(\d+)(ms|s|m|h)", s):
        val = int(m.group(1))
        unit = m.group(2)
        if unit == "ms":
            total += val / 1000.0
        elif unit == "s":
            total += val
        elif unit == "m":
            total += val * 60
        elif unit == "h":
            total += val * 3600
    if total == 0:
        try:
            total = float(s.rstrip("s"))
        except ValueError:
            total = 1.0
    return total


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_slt(filepath: str) -> List[Record]:
    """Parse an .slt file into a list of Records."""
    with open(filepath) as f:
        lines = f.readlines()

    records: List[Record] = []
    i = 0
    conditions: List[Tuple[str, str]] = []

    while i < len(lines):
        line = lines[i].rstrip("\n")
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # --- prefix directives ---
        if stripped.startswith("onlyif "):
            conditions.append(("onlyif", stripped.split(None, 1)[1]))
            i += 1
            continue
        if stripped.startswith("skipif "):
            conditions.append(("skipif", stripped.split(None, 1)[1]))
            i += 1
            continue

        # --- connection (standalone record) ---
        if stripped.startswith("connection "):
            records.append(Record(type="connection", line=i + 1,
                                  name=stripped.split(None, 1)[1]))
            i += 1
            continue

        # --- halt ---
        if stripped == "halt":
            records.append(Record(type="halt", line=i + 1))
            break

        # --- sleep ---
        if stripped.startswith("sleep "):
            records.append(Record(type="sleep", line=i + 1,
                                  duration=stripped.split(None, 1)[1]))
            i += 1
            continue

        # --- include ---
        if stripped.startswith("include "):
            pat = stripped.split(None, 1)[1]
            base = os.path.dirname(os.path.abspath(filepath))
            records.append(Record(type="include", line=i + 1, pattern=pat,
                                  base_dir=base, conditions=conditions[:]))
            conditions = []
            i += 1
            continue

        # --- hash-threshold ---
        if stripped.startswith("hash-threshold "):
            records.append(Record(type="hash-threshold", line=i + 1,
                                  threshold=int(stripped.split(None, 1)[1])))
            i += 1
            continue

        # --- subtest ---
        if stripped.startswith("subtest "):
            records.append(Record(type="subtest", line=i + 1,
                                  name=stripped.split(None, 1)[1]))
            i += 1
            continue

        # --- control ---
        if stripped.startswith("control "):
            parts = stripped.split()
            if len(parts) >= 3:
                records.append(Record(type="control", line=i + 1,
                                      setting=parts[1], value=parts[2]))
            i += 1
            continue

        # --- statement ---
        if stripped.startswith("statement "):
            rec, i = _parse_statement(lines, i, conditions[:])
            records.append(rec)
            conditions = []
            continue

        # --- query ---
        if stripped.startswith("query "):
            rec, i = _parse_query(lines, i, conditions[:])
            records.append(rec)
            conditions = []
            continue

        # --- let ---
        if stripped.startswith("let "):
            rec, i = _parse_let(lines, i, conditions[:])
            records.append(rec)
            conditions = []
            continue

        # --- system ---
        if stripped.startswith("system "):
            rec, i = _parse_system(lines, i, conditions[:])
            records.append(rec)
            conditions = []
            continue

        i += 1

    return records


def _read_body(lines: List[str], start: int):
    """Read body lines until blank line or ----. Returns (body_lines, next_i)."""
    body = []
    i = start
    while i < len(lines):
        l = lines[i].rstrip("\n")
        if l.strip() == "" or l.strip() == "----":
            break
        body.append(l)
        i += 1
    return body, i


def _read_results(lines: List[str], start: int):
    """Read result lines after ----. Returns (result_lines, next_i)."""
    results = []
    i = start
    while i < len(lines):
        l = lines[i].rstrip("\n")
        if l == "":
            i += 1
            break
        results.append(l)
        i += 1
    return results, i


def _read_multiline_error(lines: List[str], start: int):
    """Read multiline error after ---- until two consecutive blank lines."""
    error_lines = []
    blank_count = 0
    i = start
    while i < len(lines):
        l = lines[i].rstrip("\n")
        if l == "":
            blank_count += 1
            if blank_count >= 2:
                i += 1
                break
            error_lines.append("")
        else:
            blank_count = 0
            error_lines.append(l)
        i += 1
    while error_lines and error_lines[-1] == "":
        error_lines.pop()
    return "\n".join(error_lines), i


def _parse_retry(parts: List[str]):
    """Extract retry_attempts and retry_backoff from header parts."""
    retry_attempts = None
    retry_backoff = None
    for j, p in enumerate(parts):
        if p == "retry" and j + 1 < len(parts):
            retry_attempts = int(parts[j + 1])
        if p == "backoff" and j + 1 < len(parts):
            retry_backoff = parts[j + 1]
    return retry_attempts, retry_backoff


def _parse_statement(lines, start, conditions):
    header = lines[start].strip()
    parts = header.split()
    expect = parts[1]
    retry_attempts, retry_backoff = _parse_retry(parts)

    error_pattern = None
    expected_count = None
    if expect == "error":
        rest = header[header.index("error") + 5:].strip()
        rest = re.sub(r"\s*retry\s+\d+\s+backoff\s+\S+", "", rest).strip()
        if rest:
            error_pattern = rest
    elif expect == "count":
        expected_count = int(parts[2])

    i = start + 1
    sql_lines, i = _read_body(lines, i)
    sql = "\n".join(sql_lines)

    multiline_error = None
    if i < len(lines) and lines[i].strip() == "----":
        i += 1
        multiline_error, i = _read_multiline_error(lines, i)

    rec = Record(type="statement", line=start + 1, sql=sql, expect=expect,
                 error_pattern=error_pattern, multiline_error=multiline_error,
                 expected_count=expected_count, retry_attempts=retry_attempts,
                 retry_backoff=retry_backoff, conditions=conditions)
    return rec, i


def _parse_query(lines, start, conditions):
    header = lines[start].strip()
    parts = header.split()

    # --- query error ---
    if parts[1] == "error":
        rest = header[header.index("error") + 5:].strip()
        rest = re.sub(r"\s*retry\s+\d+\s+backoff\s+\S+", "", rest).strip()
        error_pattern = rest if rest else None
        retry_attempts, retry_backoff = _parse_retry(parts)

        i = start + 1
        sql_lines, i = _read_body(lines, i)
        sql = "\n".join(sql_lines)

        multiline_error = None
        if i < len(lines) and lines[i].strip() == "----":
            i += 1
            multiline_error, i = _read_multiline_error(lines, i)

        rec = Record(type="query", line=start + 1, sql=sql, expect="error",
                     error_pattern=error_pattern, multiline_error=multiline_error,
                     conditions=conditions, retry_attempts=retry_attempts,
                     retry_backoff=retry_backoff)
        return rec, i

    # --- normal query ---
    types = parts[1]
    sort_mode = None
    label = None
    retry_attempts, retry_backoff = _parse_retry(parts)

    idx = 2
    while idx < len(parts):
        if parts[idx] in ("nosort", "rowsort", "valuesort"):
            sort_mode = parts[idx]
            idx += 1
        elif parts[idx] == "retry":
            idx += 2
        elif parts[idx] == "backoff":
            idx += 2
        else:
            label = parts[idx]
            idx += 1

    i = start + 1
    sql_lines, i = _read_body(lines, i)
    sql = "\n".join(sql_lines)

    expected_results = None
    if i < len(lines) and lines[i].strip() == "----":
        i += 1
        expected_results, i = _read_results(lines, i)

    rec = Record(type="query", line=start + 1, sql=sql, expect="ok",
                 types=types, sort_mode=sort_mode, label=label,
                 expected_results=expected_results,
                 retry_attempts=retry_attempts, retry_backoff=retry_backoff,
                 conditions=conditions)
    return rec, i


def _parse_let(lines, start, conditions):
    header = lines[start].strip()
    vars_str = header[4:].strip()
    variables = [v.strip() for v in vars_str.split(",")]

    i = start + 1
    sql_lines, i = _read_body(lines, i)
    sql = "\n".join(sql_lines)
    # skip trailing blank
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    rec = Record(type="let", line=start + 1, sql=sql,
                 variables=variables, conditions=conditions)
    return rec, i


def _parse_system(lines, start, conditions):
    header = lines[start].strip()
    parts = header.split()
    expect = parts[1]
    retry_attempts, retry_backoff = _parse_retry(parts)

    i = start + 1
    cmd_lines, i = _read_body(lines, i)
    command = "\n".join(cmd_lines)

    expected_stdout = None
    if i < len(lines) and lines[i].strip() == "----":
        i += 1
        stdout_lines, i = _read_results(lines, i)
        expected_stdout = "\n".join(stdout_lines)

    rec = Record(type="system", line=start + 1, command=command,
                 expect=expect, expected_stdout=expected_stdout,
                 retry_attempts=retry_attempts, retry_backoff=retry_backoff,
                 conditions=conditions)
    return rec, i


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class SLTRunner:
    """Executes parsed SLT records against SQLite."""

    def __init__(self, db_path: Optional[str] = None,
                 labels: Optional[List[str]] = None):
        self.db_path = db_path or os.path.join(tempfile.mkdtemp(), "test.db")
        self.labels = labels or []
        self.connections: Dict[str, sqlite3.Connection] = {}
        self.current_connection = "default"
        self.variables: Dict[str, str] = {}
        self.substitution_enabled = False
        self.default_sort_mode = "nosort"
        self.result_mode = "rowwise"
        self.hash_threshold: Optional[int] = None
        self.test_dir = tempfile.mkdtemp()
        self.variables["__TEST_DIR__"] = self.test_dir

        self.total = 0
        self.passed = 0
        self.failed = 0
        self.errors: List[dict] = []

    # --- connection management ---

    def get_connection(self, name: Optional[str] = None) -> sqlite3.Connection:
        name = name or self.current_connection
        if name not in self.connections:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            self.connections[name] = conn
        return self.connections[name]

    def close_all(self):
        for conn in self.connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self.connections.clear()

    # --- substitution ---

    def apply_substitution(self, text: str) -> str:
        if not self.substitution_enabled:
            return text

        def replace_braced(m):
            var = m.group(1)
            default = m.group(3)
            if var in self.variables:
                return self.variables[var]
            env = os.environ.get(var)
            if env is not None:
                return env
            if default is not None:
                return default
            return m.group(0)

        text = re.sub(r"\$\{(\w+)(:([^}]*))?\}", replace_braced, text)

        def replace_simple(m):
            var = m.group(1)
            if var in self.variables:
                return self.variables[var]
            env = os.environ.get(var)
            if env is not None:
                return env
            return m.group(0)

        text = re.sub(r"\$(\w+)", replace_simple, text)
        return text

    # --- condition checking ---

    def check_conditions(self, conditions: List[Tuple[str, str]]) -> bool:
        for cond_type, label in conditions:
            if cond_type == "onlyif" and label not in self.labels:
                return False
            if cond_type == "skipif" and label in self.labels:
                return False
        return True

    # --- value formatting ---

    def format_value(self, val: Any, col_type: Optional[str] = None) -> str:
        if val is None:
            return "NULL"
        if col_type == "T":
            return str(val)
        if col_type == "I":
            if isinstance(val, (int, float)):
                return str(int(val))
            return str(val)
        if col_type == "R":
            if isinstance(val, (int, float)):
                return f"{float(val):.3f}"
            try:
                return f"{float(val):.3f}"
            except (ValueError, TypeError):
                return str(val)
        # No explicit type — infer from Python type
        if isinstance(val, float):
            return f"{val:.3f}"
        return str(val)

    # --- file / record dispatch ---

    def run_file(self, filepath: str):
        records = parse_slt(filepath)
        for rec in records:
            result = self.run_record(rec, filepath)
            if result == "halt":
                break

    def run_record(self, record: Record, filepath: str) -> str:
        if record.type == "halt":
            return "halt"

        if record.type == "connection":
            self.current_connection = record.name
            return "skip"

        if record.type == "control":
            if record.setting == "sortmode":
                self.default_sort_mode = record.value
            elif record.setting == "substitution":
                self.substitution_enabled = (record.value == "on")
            elif record.setting == "resultmode":
                self.result_mode = record.value
            return "skip"

        if record.type == "hash-threshold":
            self.hash_threshold = record.threshold
            return "skip"

        if record.type == "subtest":
            return "skip"

        if record.type == "sleep":
            secs = parse_duration(record.duration)
            time.sleep(secs)
            return "skip"

        if record.type == "include":
            if not self.check_conditions(record.conditions):
                return "skip"
            full_pattern = os.path.join(record.base_dir, record.pattern)
            files = sorted(globmod.glob(full_pattern))
            for f in files:
                self.run_file(f)
            return "skip"

        if record.conditions and not self.check_conditions(record.conditions):
            return "skip"

        dispatch = {
            "statement": self._run_statement,
            "query": self._run_query,
            "let": self._run_let,
            "system": self._run_system,
        }
        handler = dispatch.get(record.type)
        if handler:
            return handler(record)
        return "skip"

    # --- retry wrapper ---

    def _with_retry(self, func, record):
        attempts = record.retry_attempts or 1
        backoff = parse_duration(record.retry_backoff) if record.retry_backoff else 0
        last_result = None
        last_error = None
        for attempt in range(attempts):
            result, error = func()
            if result == "pass":
                return "pass", None
            last_result = result
            last_error = error
            if attempt < attempts - 1:
                time.sleep(backoff)
        return last_result, last_error

    # --- statement ---

    def _run_statement(self, record: Record) -> str:
        self.total += 1
        if record.retry_attempts and record.retry_attempts > 1:
            result, error = self._with_retry(
                lambda: self._exec_statement(record), record)
        else:
            result, error = self._exec_statement(record)
        if result == "pass":
            self.passed += 1
        else:
            self.failed += 1
            if error:
                self.errors.append(error)
        return result

    def _exec_statement(self, record: Record):
        sql = self.apply_substitution(record.sql)
        try:
            conn = self.get_connection()
            cursor = conn.execute(sql)
            conn.commit()
            affected = cursor.rowcount

            if record.expect == "ok":
                return "pass", None
            elif record.expect == "count":
                if affected == record.expected_count:
                    return "pass", None
                return "fail", {"line": record.line, "type": "statement",
                                "message": f"expected count {record.expected_count}, "
                                           f"got {affected}"}
            elif record.expect == "error":
                return "fail", {"line": record.line, "type": "statement",
                                "message": "expected error but statement succeeded"}
        except Exception as e:
            error_msg = str(e)
            if record.expect == "error":
                if self._match_error(error_msg, record):
                    return "pass", None
                return "fail", {"line": record.line, "type": "statement",
                                "message": f"error mismatch: {error_msg}"}
            return "fail", {"line": record.line, "type": "statement",
                            "message": f"unexpected error: {error_msg}"}
        return "fail", {"line": record.line, "type": "statement",
                        "message": "unexpected state"}

    # --- error matching ---

    def _match_error(self, error_msg: str, record: Record) -> bool:
        if record.multiline_error is not None:
            return error_msg.strip() == record.multiline_error.strip()
        if record.error_pattern:
            return bool(re.search(record.error_pattern, error_msg))
        return True  # bare error → any error matches

    # --- query ---

    def _run_query(self, record: Record) -> str:
        self.total += 1
        if record.retry_attempts and record.retry_attempts > 1:
            result, error = self._with_retry(
                lambda: self._exec_query(record), record)
        else:
            result, error = self._exec_query(record)
        if result == "pass":
            self.passed += 1
        else:
            self.failed += 1
            if error:
                self.errors.append(error)
        return result

    def _exec_query(self, record: Record):
        sql = self.apply_substitution(record.sql)
        try:
            conn = self.get_connection()
            cursor = conn.execute(sql)
            rows = cursor.fetchall()

            if record.expect == "error":
                return "fail", {"line": record.line, "type": "query",
                                "message": "expected error but query succeeded"}

            types = record.types or ""
            formatted_rows = []
            for row in rows:
                frow = []
                for j, val in enumerate(row):
                    ct = types[j] if j < len(types) else None
                    frow.append(self.format_value(val, ct))
                formatted_rows.append(frow)

            # Total values for hash-threshold
            total_values = sum(len(r) for r in formatted_rows)

            # Hash threshold check (before sorting)
            if (self.hash_threshold is not None
                    and total_values >= self.hash_threshold):
                all_vals = []
                for r in formatted_rows:
                    all_vals.extend(r)
                hash_content = "".join(v + "\n" for v in all_vals)
                hash_hex = hashlib.md5(hash_content.encode()).hexdigest()
                result_lines = [
                    f"{total_values} values hashing to {hash_hex}"]
            else:
                sort_mode = (record.sort_mode if record.sort_mode is not None
                             else self.default_sort_mode)
                if sort_mode == "valuesort":
                    values = []
                    for r in formatted_rows:
                        values.extend(r)
                    values.sort()
                    result_lines = values
                elif sort_mode == "rowsort":
                    row_strs = [" ".join(r) for r in formatted_rows]
                    row_strs.sort()
                    result_lines = row_strs
                else:  # nosort
                    result_lines = [" ".join(r) for r in formatted_rows]

            if record.expected_results is not None:
                if result_lines == record.expected_results:
                    return "pass", None
                return "fail", {
                    "line": record.line, "type": "query",
                    "message": (f"result mismatch:\n"
                                f"expected: {record.expected_results}\n"
                                f"got:      {result_lines}")}
            return "pass", None

        except Exception as e:
            error_msg = str(e)
            if record.expect == "error":
                if self._match_error(error_msg, record):
                    return "pass", None
                return "fail", {"line": record.line, "type": "query",
                                "message": f"error mismatch: {error_msg}"}
            return "fail", {"line": record.line, "type": "query",
                            "message": f"unexpected error: {error_msg}"}

    # --- let ---

    def _run_let(self, record: Record) -> str:
        self.total += 1
        result, error = self._exec_let(record)
        if result == "pass":
            self.passed += 1
        else:
            self.failed += 1
            if error:
                self.errors.append(error)
        return result

    def _exec_let(self, record: Record):
        sql = self.apply_substitution(record.sql)
        try:
            conn = self.get_connection()
            cursor = conn.execute(sql)
            rows = cursor.fetchall()

            if len(rows) != 1:
                return "fail", {"line": record.line, "type": "let",
                                "message": f"expected 1 row, got {len(rows)}"}
            row = rows[0]
            if len(row) != len(record.variables):
                return "fail", {
                    "line": record.line, "type": "let",
                    "message": (f"column count {len(row)} != "
                                f"variable count {len(record.variables)}")}
            for var, val in zip(record.variables, row):
                self.variables[var] = str(val) if val is not None else "NULL"
            return "pass", None

        except Exception as e:
            return "fail", {"line": record.line, "type": "let",
                            "message": f"error: {e}"}

    # --- system ---

    def _run_system(self, record: Record) -> str:
        self.total += 1
        if record.retry_attempts and record.retry_attempts > 1:
            result, error = self._with_retry(
                lambda: self._exec_system(record), record)
        else:
            result, error = self._exec_system(record)
        if result == "pass":
            self.passed += 1
        else:
            self.failed += 1
            if error:
                self.errors.append(error)
        return result

    def _exec_system(self, record: Record):
        command = record.command
        for var, val in self.variables.items():
            command = command.replace(f"${{{var}}}", val)
            command = command.replace(f"${var}", val)

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30)

            if record.expect == "ok":
                if result.returncode != 0:
                    return "fail", {
                        "line": record.line, "type": "system",
                        "message": (f"command failed (exit {result.returncode}): "
                                    f"{result.stderr.strip()}")}
                if record.expected_stdout is not None:
                    actual = result.stdout.rstrip("\n")
                    expected = record.expected_stdout.rstrip("\n")
                    if actual == expected:
                        return "pass", None
                    return "fail", {
                        "line": record.line, "type": "system",
                        "message": (f"stdout mismatch:\n"
                                    f"expected: {expected}\n"
                                    f"got:      {actual}")}
                return "pass", None
            return "fail", {"line": record.line, "type": "system",
                            "message": "unexpected result"}

        except subprocess.TimeoutExpired:
            return "fail", {"line": record.line, "type": "system",
                            "message": "command timed out"}
        except Exception as e:
            return "fail", {"line": record.line, "type": "system",
                            "message": f"error: {e}"}

    # --- report ---

    def get_report(self, filepath: str) -> dict:
        return {
            "file": filepath,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="sqllogictest runner for SQLite")
    parser.add_argument("file", help="SLT file to run")
    parser.add_argument("--label", action="append", default=[],
                        help="Labels for skipif/onlyif (repeatable)")
    parser.add_argument("--db", default=None,
                        help="SQLite database path (default: temp file)")
    args = parser.parse_args()

    runner = SLTRunner(db_path=args.db, labels=args.label)
    try:
        runner.run_file(args.file)
    finally:
        runner.close_all()

    report = runner.get_report(args.file)
    print(json.dumps(report))
    sys.exit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    main()

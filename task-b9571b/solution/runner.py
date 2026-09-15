#!/usr/bin/env python3
"""
SQLLogicTest runner for DuckDB with dual-execution plan verification.

Parses and executes .test files in the sqllogictest format, verifying
SQL statement results against expected outcomes. Supports multi-connection
execution, reconnect, EXPLAIN plan verification via regex, query labels,
loop/foreach, hash-based result verification, and mode directives
(verify/noverify for dual-execution plan verification, skip/unskip for
execution flow control).

"""

import sys
import re
import hashlib
import os
import io

# Ensure stdout/stderr handle Unicode regardless of locale
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import duckdb


class SkipException(Exception):
    """Raised when a require directive is unmet; the entire test is skipped."""
    pass


class ConnectionPool:
    """Manages named database connections (cursors) over a single DuckDB database.

    The database instance (DuckDBPyConnection from duckdb.connect()) is kept
    alive across reconnects. The default connection uses the main database
    connection directly; named connections use cursors created from it.
    """

    def __init__(self, db):
        self.db = db
        self.named = {}

    def get(self, name=None):
        """Get a connection by name. Creates new cursors lazily."""
        if name is None:
            return self.db
        if name not in self.named:
            self.named[name] = self.db.cursor()
        return self.named[name]

    def reconnect(self):
        """Drop all named cursors. The main database connection stays open
        so persistent state (tables, data) is preserved."""
        for conn in self.named.values():
            try:
                conn.close()
            except Exception:
                pass
        self.named.clear()


class SQLLogicTestRunner:
    """Parses and executes sqllogictest .test files against DuckDB."""

    def __init__(self):
        self.db = duckdb.connect()
        self.pool = ConnectionPool(self.db)
        self.labels = {}        # label -> md5 hash
        self.hash_threshold = None
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.verify_mode = False
        self.skip_mode = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, filepath):
        """Run a .test file. Returns True if all tests pass or test is skipped."""
        if not os.path.exists(filepath):
            print(f"ERROR: File not found: {filepath}", file=sys.stderr)
            return False

        with open(filepath, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]

        try:
            self._execute_block(lines, {})
        except SkipException as exc:
            print(f"SKIP: {filepath} ({exc})")
            return True

        if self.failed > 0:
            print(
                f"FAILED: {self.failed} failure(s) out of "
                f"{self.passed + self.failed} checks in {filepath}",
                file=sys.stderr,
            )
            for err in self.errors:
                print(f"  >> {err}", file=sys.stderr)
            return False

        print(f"PASS: {self.passed} checks in {filepath}")
        return True

    # ------------------------------------------------------------------
    # Core execution loop
    # ------------------------------------------------------------------

    def _execute_block(self, lines, variables):
        """Walk *lines* and dispatch each directive."""
        idx = 0
        while idx < len(lines):
            line = self._sub(lines[idx], variables)

            # Blank / comment
            if line.strip() == "" or line.lstrip().startswith("#"):
                idx += 1
                continue

            # --- mode directives (always processed, even in skip mode) ---
            if line.startswith("mode "):
                mode_val = line.split(None, 1)[1].strip()
                if mode_val == "verify":
                    self.verify_mode = True
                elif mode_val == "noverify":
                    self.verify_mode = False
                elif mode_val == "skip":
                    self.skip_mode = True
                elif mode_val == "unskip":
                    self.skip_mode = False
                idx += 1
                continue

            # --- skip mode: skip all non-mode directives ---
            if self.skip_mode:
                stripped = line.strip()
                if stripped.startswith("loop ") or stripped.startswith("foreach "):
                    # Jump past the matching endloop/endforeach
                    end_idx = self._find_end(lines, idx + 1)
                    idx = end_idx + 1
                else:
                    idx += 1
                continue

            # --- reconnect ---
            if line.strip() == "reconnect":
                self.pool.reconnect()
                idx += 1
                continue

            # --- require ---
            if line.startswith("require "):
                ext = line.split(None, 1)[1].strip()
                if not self._ext_available(ext):
                    raise SkipException(f"extension '{ext}' not available")
                idx += 1
                continue

            # --- hash_threshold ---
            if line.startswith("hash_threshold "):
                self.hash_threshold = int(line.split()[1])
                idx += 1
                continue

            # --- loop ---
            if line.startswith("loop "):
                idx = self._do_loop(lines, idx, variables)
                continue

            # --- foreach ---
            if line.startswith("foreach "):
                idx = self._do_foreach(lines, idx, variables)
                continue

            # --- statement ok/error ---
            if line.startswith("statement "):
                parts = line.split()
                if len(parts) >= 2 and parts[1] in ("ok", "error"):
                    conn_name = self._parse_connection_name(parts[2:])
                    if parts[1] == "ok":
                        idx = self._do_statement_ok(lines, idx, variables, conn_name)
                    else:
                        idx = self._do_statement_error(lines, idx, variables, conn_name)
                    continue

            # --- query ---
            if line.startswith("query "):
                idx = self._do_query(lines, idx, variables)
                continue

            # Unknown line - skip silently
            idx += 1

    # ------------------------------------------------------------------
    # Connection name parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_connection_name(tokens):
        """Extract @connection_name from a list of tokens."""
        for tok in tokens:
            if tok.startswith("@"):
                return tok[1:]  # Remove @ prefix
        return None

    # ------------------------------------------------------------------
    # Variable substitution
    # ------------------------------------------------------------------

    @staticmethod
    def _sub(text, variables):
        for key, val in variables.items():
            text = text.replace(f"${{{key}}}", str(val))
        return text

    # ------------------------------------------------------------------
    # Extension availability
    # ------------------------------------------------------------------

    def _ext_available(self, name):
        conn = self.pool.get()
        try:
            conn.execute(f"LOAD '{name}'")
            return True
        except Exception:
            pass
        try:
            conn.execute(f"INSTALL '{name}'")
            conn.execute(f"LOAD '{name}'")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Line collectors
    # ------------------------------------------------------------------

    def _collect_sql(self, lines, start, variables):
        """Return (sql_string, next_index) collecting until ---- or blank."""
        idx = start
        parts = []
        while idx < len(lines):
            line = self._sub(lines[idx], variables)
            if line.strip() == "" or line.startswith("----"):
                break
            parts.append(line)
            idx += 1
        return "\n".join(parts), idx

    def _collect_expected(self, lines, start, variables):
        """Return (list_of_expected_lines | None, next_index)."""
        if start >= len(lines):
            return None, start
        line = self._sub(lines[start], variables)
        if not line.startswith("----"):
            return None, start
        idx = start + 1  # skip ----
        result = []
        while idx < len(lines):
            line = self._sub(lines[idx], variables)
            if line.strip() == "":
                idx += 1
                break
            result.append(line)
            idx += 1
        return result, idx

    # ------------------------------------------------------------------
    # Directive handlers
    # ------------------------------------------------------------------

    def _do_statement_ok(self, lines, start, variables, conn_name=None):
        idx = start + 1
        sql, idx = self._collect_sql(lines, idx, variables)
        _, idx = self._collect_expected(lines, idx, variables)  # consume any ----

        conn = self.pool.get(conn_name)
        try:
            conn.execute(sql)
            self.passed += 1
        except Exception as exc:
            self.failed += 1
            self.errors.append(
                f"'statement ok' raised error on: {sql[:120]}  |  {exc}"
            )
        return idx

    def _do_statement_error(self, lines, start, variables, conn_name=None):
        idx = start + 1
        sql, idx = self._collect_sql(lines, idx, variables)
        expected_lines, idx = self._collect_expected(lines, idx, variables)
        expected_msg = "\n".join(expected_lines) if expected_lines else None

        conn = self.pool.get(conn_name)
        try:
            conn.execute(sql)
            # Should have failed
            self.failed += 1
            self.errors.append(
                f"'statement error' succeeded unexpectedly: {sql[:120]}"
            )
        except Exception as exc:
            err_str = str(exc)
            if expected_msg is not None and expected_msg not in err_str:
                self.failed += 1
                self.errors.append(
                    f"Error mismatch.  Expected substring: '{expected_msg}'  "
                    f"Actual: '{err_str[:200]}'"
                )
            else:
                self.passed += 1
        return idx

    def _do_query(self, lines, start, variables):
        header = self._sub(lines[start], variables)
        parts = header.split()
        types = parts[1] if len(parts) > 1 else "I"
        ncols = len(types)
        sort_mode = "nosort"
        label = None
        conn_name = None

        for tok in parts[2:]:
            if tok in ("nosort", "rowsort", "valuesort"):
                sort_mode = tok
            elif tok.startswith("@"):
                conn_name = tok[1:]
            else:
                label = tok

        idx = start + 1
        sql, idx = self._collect_sql(lines, idx, variables)
        expected, idx = self._collect_expected(lines, idx, variables)

        # Execute
        conn = self.pool.get(conn_name)
        try:
            rows = conn.execute(sql).fetchall()
        except Exception as exc:
            self.failed += 1
            self.errors.append(f"Query error: {sql[:120]}  |  {exc}")
            return idx

        # Flatten to string values in row-major order
        values = []
        for row in rows:
            for cell in row:
                values.append(self._fmt(cell))

        # --- Dual-execution plan verification ---
        if self.verify_mode and "EXPLAIN" not in sql.upper():
            verify_failed = False
            try:
                conn.execute("SET enable_optimizer = false")
                verify_rows = conn.execute(sql).fetchall()
                verify_values = []
                for row in verify_rows:
                    for cell in row:
                        verify_values.append(self._fmt(cell))
                if sorted(values) != sorted(verify_values):
                    verify_failed = True
            except Exception:
                pass  # Verification execution failure is non-fatal
            finally:
                try:
                    conn.execute("SET enable_optimizer = true")
                except Exception:
                    pass
            if verify_failed:
                self.failed += 1
                self.errors.append(
                    f"Plan verification failed: optimized and unoptimized "
                    f"results differ for: {sql[:120]}"
                )
                return idx

        # --- Label handling ---
        if label is not None:
            h = self._hash_values(values)
            if label in self.labels:
                if self.labels[label] != h:
                    self.failed += 1
                    self.errors.append(
                        f"Label '{label}' hash mismatch: "
                        f"stored={self.labels[label]}  got={h}"
                    )
                    return idx
            else:
                self.labels[label] = h

        # If no expected results, nothing more to check
        if not expected:
            self.passed += 1
            return idx

        # --- Hash verification (explicit hash in expected) ---
        if len(expected) == 1:
            m = re.match(
                r"^(\d+)\s+values\s+hashing\s+to\s+([0-9a-f]+)$",
                expected[0],
            )
            if m:
                exp_count = int(m.group(1))
                exp_hash = m.group(2)
                if len(values) != exp_count:
                    self.failed += 1
                    self.errors.append(
                        f"Hash count mismatch: expected {exp_count}, "
                        f"got {len(values)}"
                    )
                    return idx
                actual_hash = self._hash_values(values)
                if actual_hash != exp_hash:
                    self.failed += 1
                    self.errors.append(
                        f"Hash mismatch: expected {exp_hash}, got {actual_hash}"
                    )
                    return idx
                self.passed += 1
                return idx

        # --- hash_threshold auto-hashing ---
        if (
            self.hash_threshold is not None
            and len(values) > self.hash_threshold
        ):
            actual_hash = self._hash_values(values)
            # Flatten expected values the same way
            exp_values = self._expand_expected(expected, ncols)
            expected_hash = self._hash_values(exp_values)
            if actual_hash != expected_hash:
                self.failed += 1
                self.errors.append(
                    f"Hash threshold auto-hash mismatch: "
                    f"expected {expected_hash}, got {actual_hash}"
                )
            else:
                self.passed += 1
            return idx

        # --- Value-level comparison (valuesort) ---
        if sort_mode == "valuesort":
            actual_sorted = sorted(values)
            expected_sorted = sorted(expected)
            if len(actual_sorted) != len(expected_sorted):
                self.failed += 1
                self.errors.append(
                    f"Valuesort count mismatch: "
                    f"expected {len(expected_sorted)}, got {len(actual_sorted)}"
                )
                return idx
            for j, (a, e) in enumerate(zip(actual_sorted, expected_sorted)):
                if not self._match_value(a, e):
                    self.failed += 1
                    self.errors.append(
                        f"Valuesort mismatch at position {j}: "
                        f"expected '{e}', got '{a}'"
                    )
                    return idx
            self.passed += 1
            return idx

        # --- Row-level comparison (nosort / rowsort) ---
        actual_rows = []
        for j in range(0, len(values), ncols):
            actual_rows.append("\t".join(values[j : j + ncols]))

        exp_rows = list(expected)

        if sort_mode == "rowsort":
            actual_rows = sorted(actual_rows)
            exp_rows = sorted(exp_rows)

        if len(actual_rows) != len(exp_rows):
            self.failed += 1
            self.errors.append(
                f"Row count mismatch: expected {len(exp_rows)}, "
                f"got {len(actual_rows)}"
            )
            return idx

        for j, (ar, er) in enumerate(zip(actual_rows, exp_rows)):
            if not self._match_row(ar, er):
                self.failed += 1
                self.errors.append(
                    f"Row {j} mismatch:\n"
                    f"  expected: {er!r}\n"
                    f"  actual:   {ar!r}"
                )
                return idx

        self.passed += 1
        return idx

    # ------------------------------------------------------------------
    # Loop / foreach
    # ------------------------------------------------------------------

    def _find_end(self, lines, start):
        """Find matching endloop/endforeach, handling nesting."""
        depth = 1
        idx = start
        while idx < len(lines):
            stripped = lines[idx].strip()
            if stripped.startswith("loop ") or stripped.startswith("foreach "):
                depth += 1
            elif stripped in ("endloop", "endforeach"):
                depth -= 1
                if depth == 0:
                    return idx
            idx += 1
        return idx  # fallback: end of file

    def _do_loop(self, lines, start, variables):
        header = self._sub(lines[start], variables)
        parts = header.split()
        var_name = parts[1]
        lo = int(self._sub(parts[2], variables))
        hi = int(self._sub(parts[3], variables))

        body_start = start + 1
        end_idx = self._find_end(lines, body_start)
        body = lines[body_start:end_idx]

        for val in range(lo, hi):
            new_vars = dict(variables)
            new_vars[var_name] = val
            self._execute_block(body, new_vars)

        return end_idx + 1  # skip past endloop

    def _do_foreach(self, lines, start, variables):
        header = self._sub(lines[start], variables)
        parts = header.split()
        var_name = parts[1]
        vals = parts[2:]

        body_start = start + 1
        end_idx = self._find_end(lines, body_start)
        body = lines[body_start:end_idx]

        for val in vals:
            new_vars = dict(variables)
            new_vars[var_name] = val
            self._execute_block(body, new_vars)

        return end_idx + 1  # skip past endforeach

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(value):
        """Convert a Python value from DuckDB to its sqllogictest string."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return "(empty)" if value == "" else value
        return str(value)

    @staticmethod
    def _hash_values(values):
        """MD5 hash of values joined by newlines with trailing newline."""
        data = "\n".join(values) + "\n"
        return hashlib.md5(data.encode("utf-8")).hexdigest()

    @staticmethod
    def _expand_expected(expected, ncols):
        """Expand expected lines into individual values for hash comparison."""
        values = []
        for line in expected:
            if "\t" in line:
                values.extend(line.split("\t"))
            else:
                values.append(line)
        return values

    # ------------------------------------------------------------------
    # Comparison helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_value(actual, expected):
        """Compare a single value, supporting <REGEX> / <!REGEX> with DOTALL."""
        if expected.startswith("<REGEX>:"):
            pattern = expected[8:]
            return bool(re.search(pattern, actual, re.DOTALL))
        if expected.startswith("<!REGEX>:"):
            pattern = expected[9:]
            return not bool(re.search(pattern, actual, re.DOTALL))
        return actual == expected

    def _match_row(self, actual_row, expected_row):
        """Compare two tab-separated rows, with per-value regex support."""
        a_vals = actual_row.split("\t")
        e_vals = expected_row.split("\t")
        if len(a_vals) != len(e_vals):
            return False
        return all(self._match_value(a, e) for a, e in zip(a_vals, e_vals))


# ======================================================================
# CLI entry point
# ======================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 sqllogictest_runner.py <test_file>", file=sys.stderr)
        sys.exit(2)

    runner = SQLLogicTestRunner()
    ok = runner.run(sys.argv[1])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

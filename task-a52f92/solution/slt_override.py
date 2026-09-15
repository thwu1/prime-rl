#!/usr/bin/env python3
"""
sqllogictest --override module.

Rewrites .slt files in-place with actual database output.
Designed to match the semantics of sqllogictest-rs update_record_with_output.

"""

import re
import os
import sys
import sqlite3
import hashlib
import subprocess
import tempfile
import time
import glob as globmod
from typing import Optional, List, Dict, Tuple, Any

# Add /app to path so we can import parse_duration
sys.path.insert(0, "/app")


def override_file(filepath: str, db_path: Optional[str] = None,
                  labels: Optional[List[str]] = None):
    """Override an .slt file with actual database output."""
    with open(filepath) as f:
        original_lines = f.readlines()

    ctx = _OverrideContext(db_path=db_path, labels=labels or [])
    try:
        new_content = ctx.process_lines(original_lines, filepath)
    finally:
        ctx.close_all()

    with open(filepath, "w") as f:
        f.write(new_content)
        f.flush()
        os.fsync(f.fileno())


class _OverrideContext:
    """Maintains state while processing an .slt file for override."""

    def __init__(self, db_path=None, labels=None):
        self.db_path = db_path or os.path.join(tempfile.mkdtemp(), "test.db")
        self.labels = labels or []
        self.connections: Dict[str, sqlite3.Connection] = {}
        self.current_connection = "default"
        self.variables: Dict[str, str] = {}
        self.substitution_enabled = False
        self.default_sort_mode = "nosort"
        self.hash_threshold: Optional[int] = None
        self.test_dir = tempfile.mkdtemp()
        self.variables["__TEST_DIR__"] = self.test_dir

    def get_connection(self, name=None):
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

    def check_conditions(self, conditions):
        for cond_type, label in conditions:
            if cond_type == "onlyif" and label not in self.labels:
                return False
            if cond_type == "skipif" and label in self.labels:
                return False
        return True

    def apply_substitution(self, text):
        if not self.substitution_enabled:
            return text
        # Handle escape sequences
        text = text.replace("\\$", "\x00ESC_DOLLAR\x00")
        text = text.replace("\\\\", "\x00ESC_BSLASH\x00")

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

        text = text.replace("\x00ESC_DOLLAR\x00", "$")
        text = text.replace("\x00ESC_BSLASH\x00", "\\")
        return text

    def format_value(self, val, col_type=None):
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
        if isinstance(val, float):
            return f"{val:.3f}"
        return str(val)

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

    def process_lines(self, lines, filepath):
        """Process all lines and produce overridden content."""
        out = []
        i = 0
        halt = False
        conditions: List[Tuple[str, str]] = []

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # After halt: pass through everything unchanged
            if halt:
                out.append(line)
                i += 1
                continue

            # Blank lines and comments: pass through
            if not stripped or stripped.startswith("#"):
                out.append(line)
                i += 1
                continue

            # Condition directives: accumulate and pass through
            if stripped.startswith("onlyif "):
                conditions.append(("onlyif", stripped.split(None, 1)[1]))
                out.append(line)
                i += 1
                continue
            if stripped.startswith("skipif "):
                conditions.append(("skipif", stripped.split(None, 1)[1]))
                out.append(line)
                i += 1
                continue

            # Halt: set flag and pass through
            if stripped == "halt":
                halt = True
                out.append(line)
                i += 1
                conditions = []
                continue

            # Control directives: update state and pass through
            if stripped.startswith("control "):
                parts = stripped.split()
                if len(parts) >= 3:
                    if parts[1] == "sortmode":
                        self.default_sort_mode = parts[2]
                    elif parts[1] == "substitution":
                        self.substitution_enabled = (parts[2] == "on")
                out.append(line)
                i += 1
                conditions = []
                continue

            # Hash-threshold: update state and pass through
            if stripped.startswith("hash-threshold "):
                self.hash_threshold = int(stripped.split(None, 1)[1])
                out.append(line)
                i += 1
                conditions = []
                continue

            # Connection: update state and pass through
            if stripped.startswith("connection "):
                self.current_connection = stripped.split(None, 1)[1]
                out.append(line)
                i += 1
                conditions = []
                continue

            # Simple pass-through directives
            if stripped.startswith(("subtest ", "sleep ")):
                out.append(line)
                i += 1
                conditions = []
                continue

            # Include: pass through (override of included files not supported)
            if stripped.startswith("include "):
                out.append(line)
                i += 1
                conditions = []
                continue

            # Check conditions for the upcoming record
            should_skip = not self.check_conditions(conditions)
            conditions = []

            if should_skip:
                # Pass through entire record unchanged
                i = self._passthrough_record(lines, i, out)
                continue

            # Dispatch to record handlers
            if stripped.startswith("statement "):
                i = self._process_statement(lines, i, out)
            elif stripped.startswith("query "):
                i = self._process_query(lines, i, out)
            elif stripped.startswith("system "):
                i = self._process_system(lines, i, out)
            elif stripped.startswith("let "):
                i = self._process_let(lines, i, out)
            else:
                out.append(line)
                i += 1

        return "".join(out)

    # ------------------------------------------------------------------
    # Pass-through helper (for skipped records)
    # ------------------------------------------------------------------

    def _passthrough_record(self, lines, start, out):
        """Pass through an entire record unchanged, returning next index."""
        out.append(lines[start])
        i = start + 1
        # Read body until blank or ----
        while i < len(lines):
            l = lines[i]
            if l.strip() == "":
                out.append(l)
                i += 1
                break
            if l.strip() == "----":
                out.append(l)
                i += 1
                # Determine termination mode from record type
                header = lines[start].strip()
                if header.startswith("system ") or (
                    header.startswith("statement ") and "error" in header
                ):
                    # Double-blank-line termination
                    i = self._passthrough_double_blank(lines, i, out)
                else:
                    # Single-blank-line termination (query results)
                    while i < len(lines):
                        out.append(lines[i])
                        if lines[i].strip() == "":
                            i += 1
                            break
                        i += 1
                return i
            out.append(l)
            i += 1
        return i

    def _passthrough_double_blank(self, lines, start, out):
        """Pass through lines until two consecutive blank lines."""
        i = start
        blank_count = 0
        while i < len(lines):
            l = lines[i]
            out.append(l)
            if l.strip() == "":
                blank_count += 1
                if blank_count >= 2:
                    i += 1
                    break
            else:
                blank_count = 0
            i += 1
        return i

    # ------------------------------------------------------------------
    # Read helpers (consume old content without writing)
    # ------------------------------------------------------------------

    def _read_body(self, lines, start):
        """Read body lines (SQL/command) until blank or ----."""
        body = []
        i = start
        while i < len(lines):
            l = lines[i].rstrip("\n")
            if l.strip() == "" or l.strip() == "----":
                break
            body.append(l)
            i += 1
        return body, i

    def _skip_single_blank_results(self, lines, start):
        """Skip past results terminated by single blank line (query results)."""
        i = start
        while i < len(lines):
            if lines[i].strip() == "":
                i += 1
                break
            i += 1
        return i

    def _skip_double_blank_results(self, lines, start):
        """Skip past results terminated by two consecutive blank lines."""
        i = start
        blank_count = 0
        while i < len(lines):
            if lines[i].strip() == "":
                blank_count += 1
                if blank_count >= 2:
                    i += 1
                    break
            else:
                blank_count = 0
            i += 1
        return i

    # ------------------------------------------------------------------
    # Statement processing
    # ------------------------------------------------------------------

    def _process_statement(self, lines, start, out):
        """Process a statement record with potential override."""
        header = lines[start].rstrip("\n")
        parts = header.split()
        expect = parts[1]

        # Extract expected count
        expected_count = None
        if expect == "count" and len(parts) >= 3:
            expected_count = int(parts[2])

        # Read SQL body
        i = start + 1
        sql_lines, i = self._read_body(lines, i)
        sql = "\n".join(sql_lines)

        # Skip past old results section (if any)
        if i < len(lines) and lines[i].strip() == "----":
            i += 1
            i = self._skip_double_blank_results(lines, i)
        elif i < len(lines) and lines[i].strip() == "":
            i += 1

        # Execute
        applied_sql = self.apply_substitution(sql)
        try:
            conn = self.get_connection()
            cursor = conn.execute(applied_sql)
            conn.commit()
            affected = cursor.rowcount

            # Success path
            if expect == "count":
                out.append(f"statement count {affected}\n")
            elif expect == "error":
                # Error expected but succeeded -> convert to ok
                out.append("statement ok\n")
            else:
                out.append("statement ok\n")

            for sl in sql_lines:
                out.append(sl + "\n")
            out.append("\n")

        except Exception as e:
            error_msg = str(e).strip()

            # Error path -- write as statement error with actual error
            err_lines = error_msg.split("\n")
            if len(err_lines) > 1:
                # Multi-line error -> multiline format with ---- and double blank
                out.append("statement error\n")
                for sl in sql_lines:
                    out.append(sl + "\n")
                out.append("----\n")
                for el in err_lines:
                    out.append(el + "\n")
                out.append("\n")
                out.append("\n")
            else:
                # Single-line error -> inline regex format
                escaped = re.escape(error_msg)
                out.append(f"statement error {escaped}\n")
                for sl in sql_lines:
                    out.append(sl + "\n")
                out.append("\n")

        return i

    # ------------------------------------------------------------------
    # Query processing
    # ------------------------------------------------------------------

    def _process_query(self, lines, start, out):
        """Process a query record with potential override."""
        header = lines[start].rstrip("\n")
        parts = header.split()

        # Handle "query error" separately
        if parts[1] == "error":
            return self._process_query_error(lines, start, out)

        types_str = parts[1]
        sort_mode = None
        label = None

        idx = 2
        while idx < len(parts):
            if parts[idx] in ("nosort", "rowsort", "valuesort"):
                sort_mode = parts[idx]
                idx += 1
            elif parts[idx] in ("retry", "backoff"):
                idx += 2
            else:
                label = parts[idx]
                idx += 1

        # Read SQL
        i = start + 1
        sql_lines, i = self._read_body(lines, i)
        sql = "\n".join(sql_lines)

        # Skip old results
        if i < len(lines) and lines[i].strip() == "----":
            i += 1
            i = self._skip_single_blank_results(lines, i)
        elif i < len(lines) and lines[i].strip() == "":
            i += 1

        # Execute
        applied_sql = self.apply_substitution(sql)
        try:
            conn = self.get_connection()
            cursor = conn.execute(applied_sql)
            rows = cursor.fetchall()

            # Format results
            formatted_rows = []
            for row in rows:
                frow = []
                for j, val in enumerate(row):
                    ct = types_str[j] if j < len(types_str) else None
                    frow.append(self.format_value(val, ct))
                formatted_rows.append(frow)

            # Apply sort mode
            effective_sort = sort_mode if sort_mode is not None else self.default_sort_mode

            if effective_sort == "valuesort":
                all_vals = []
                for r in formatted_rows:
                    all_vals.extend(r)
                all_vals.sort()
                result_lines = all_vals
                total_values = len(all_vals)
            elif effective_sort == "rowsort":
                row_strs = [" ".join(r) for r in formatted_rows]
                row_strs.sort()
                result_lines = row_strs
                total_values = sum(len(r) for r in formatted_rows)
            else:
                result_lines = [" ".join(r) for r in formatted_rows]
                total_values = sum(len(r) for r in formatted_rows)

            # Apply hash-threshold
            if (self.hash_threshold is not None
                    and self.hash_threshold > 0
                    and total_values > self.hash_threshold):
                if effective_sort == "valuesort":
                    hash_vals = all_vals
                else:
                    hash_vals = []
                    for r in formatted_rows:
                        hash_vals.extend(r)
                hash_content = "".join(v + "\n" for v in hash_vals)
                hash_hex = hashlib.md5(hash_content.encode()).hexdigest()
                result_lines = [f"{total_values} values hashing to {hash_hex}"]

            # Write updated record -- preserve original header
            out.append(header + "\n")
            for sl in sql_lines:
                out.append(sl + "\n")
            out.append("----\n")
            for rl in result_lines:
                out.append(rl + "\n")
            out.append("\n")

        except Exception as e:
            error_msg = str(e).strip()
            err_lines = error_msg.split("\n")

            if len(err_lines) > 1:
                out.append("query error\n")
                for sl in sql_lines:
                    out.append(sl + "\n")
                out.append("----\n")
                for el in err_lines:
                    out.append(el + "\n")
                out.append("\n")
                out.append("\n")
            else:
                escaped = re.escape(error_msg)
                out.append(f"query error {escaped}\n")
                for sl in sql_lines:
                    out.append(sl + "\n")
                out.append("\n")

        return i

    def _process_query_error(self, lines, start, out):
        """Process a 'query error' record with override."""
        header = lines[start].rstrip("\n")

        # Read SQL
        i = start + 1
        sql_lines, i = self._read_body(lines, i)
        sql = "\n".join(sql_lines)

        # Skip old results/error
        if i < len(lines) and lines[i].strip() == "----":
            i += 1
            i = self._skip_double_blank_results(lines, i)
        elif i < len(lines) and lines[i].strip() == "":
            i += 1

        # Execute
        applied_sql = self.apply_substitution(sql)
        try:
            conn = self.get_connection()
            cursor = conn.execute(applied_sql)
            rows = cursor.fetchall()

            # Query succeeded but error was expected -> write results
            ncols = len(rows[0]) if rows else 0
            types_str = "T" * ncols
            result_lines = []
            for row in rows:
                result_lines.append(" ".join(str(v) if v is not None else "NULL"
                                            for v in row))

            out.append(f"query {types_str} nosort\n")
            for sl in sql_lines:
                out.append(sl + "\n")
            out.append("----\n")
            for rl in result_lines:
                out.append(rl + "\n")
            out.append("\n")

        except Exception as e:
            # Error occurred as expected -> update error message
            error_msg = str(e).strip()
            err_lines = error_msg.split("\n")
            if len(err_lines) > 1:
                out.append("query error\n")
                for sl in sql_lines:
                    out.append(sl + "\n")
                out.append("----\n")
                for el in err_lines:
                    out.append(el + "\n")
                out.append("\n")
                out.append("\n")
            else:
                escaped = re.escape(error_msg)
                out.append(f"query error {escaped}\n")
                for sl in sql_lines:
                    out.append(sl + "\n")
                out.append("\n")

        return i

    # ------------------------------------------------------------------
    # System processing
    # ------------------------------------------------------------------

    def _process_system(self, lines, start, out):
        """Process a system record with override."""
        header = lines[start].rstrip("\n")

        # Read command body
        i = start + 1
        cmd_lines, i = self._read_body(lines, i)
        command = "\n".join(cmd_lines)

        # Skip old stdout section
        had_stdout = False
        if i < len(lines) and lines[i].strip() == "----":
            had_stdout = True
            i += 1
            i = self._skip_double_blank_results(lines, i)
        elif i < len(lines) and lines[i].strip() == "":
            i += 1

        # Execute command with variable substitution
        cmd = command
        for var, val in self.variables.items():
            cmd = cmd.replace(f"${{{var}}}", val)
            cmd = cmd.replace(f"${var}", val)

        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True,
                                  text=True, timeout=30)

            out.append("system ok\n")
            for cl in cmd_lines:
                out.append(cl + "\n")

            stdout = proc.stdout.rstrip("\n")
            if had_stdout or stdout:
                out.append("----\n")
                if stdout:
                    for sl in stdout.split("\n"):
                        out.append(sl + "\n")
                out.append("\n")
                out.append("\n")
            else:
                out.append("\n")

        except Exception:
            # On execution error, preserve original
            out.append(lines[start])
            for cl in cmd_lines:
                out.append(cl + "\n")
            out.append("\n")

        return i

    # ------------------------------------------------------------------
    # Let processing (execute for state, pass through unchanged)
    # ------------------------------------------------------------------

    def _process_let(self, lines, start, out):
        """Process a let record -- execute for state but pass through."""
        header = lines[start].rstrip("\n")
        vars_str = header[4:].strip()
        variables = [v.strip() for v in vars_str.split(",")]

        i = start + 1
        sql_lines, i = self._read_body(lines, i)
        sql = "\n".join(sql_lines)

        # Skip trailing blank
        if i < len(lines) and lines[i].strip() == "":
            i += 1

        # Execute to update state
        applied_sql = self.apply_substitution(sql)
        try:
            conn = self.get_connection()
            cursor = conn.execute(applied_sql)
            rows = cursor.fetchall()
            if len(rows) == 1 and len(rows[0]) == len(variables):
                for var, val in zip(variables, rows[0]):
                    self.variables[var] = str(val) if val is not None else "NULL"
        except Exception:
            pass

        # Pass through unchanged
        out.append(lines[start])
        for sl in sql_lines:
            out.append(sl + "\n")
        out.append("\n")

        return i

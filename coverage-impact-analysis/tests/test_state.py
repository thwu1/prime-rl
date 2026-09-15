
import configparser
import json
import os
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# 1. Verify the .coveragerc was correctly fixed (all 5 bugs)
# ---------------------------------------------------------------------------

class TestCoverageConfig:
    """Verify .coveragerc has all 5 bugs fixed."""

    @pytest.fixture(autouse=True)
    def _load_config(self):
        self.config = configparser.ConfigParser()
        files_read = self.config.read('/app/.coveragerc')
        assert files_read, ".coveragerc must exist and be readable"

    def test_source_is_src(self):
        source = self.config.get('run', 'source')
        assert 'src' in source, f"[run] source should reference 'src', got: {source}"
        assert 'lib' not in source, f"[run] source should not reference 'lib', got: {source}"

    def test_branch_enabled(self):
        branch = self.config.getboolean('run', 'branch')
        assert branch is True, "[run] branch must be true for arc-based data"

    def test_dynamic_context_is_test_function(self):
        dc = self.config.get('run', 'dynamic_context').strip()
        assert dc == 'test_function', (
            f"[run] dynamic_context must be 'test_function', got: {dc!r}"
        )

    def test_exclude_lines_no_raise_pattern(self):
        excludes = self.config.get('report', 'exclude_lines', fallback='')
        lines = [l.strip() for l in excludes.strip().split('\n') if l.strip()]
        raise_patterns = [l for l in lines if l.startswith('raise')]
        assert len(raise_patterns) == 0, (
            f"[report] exclude_lines should not contain raise patterns: "
            f"{raise_patterns}"
        )

    def test_json_show_contexts(self):
        show = self.config.getboolean('json', 'show_contexts')
        assert show is True, "[json] show_contexts must be true"


# ---------------------------------------------------------------------------
# 2. Verify coverage data was collected correctly
# ---------------------------------------------------------------------------

class TestCoverageDatabase:
    """Verify the .coverage SQLite database has proper data."""

    def test_database_exists(self):
        assert os.path.exists('/app/.coverage'), (
            ".coverage database must exist — did you run 'coverage run -m pytest'?"
        )

    def test_has_arc_data(self):
        conn = sqlite3.connect('/app/.coverage')
        try:
            count = conn.execute("SELECT COUNT(*) FROM arc").fetchone()[0]
        finally:
            conn.close()
        assert count > 0, "arc table should have data (branch coverage must be on)"

    def test_has_dynamic_contexts(self):
        conn = sqlite3.connect('/app/.coverage')
        try:
            rows = conn.execute(
                "SELECT context FROM context WHERE context != ''"
            ).fetchall()
        finally:
            conn.close()
        contexts = [r[0] for r in rows]
        assert len(contexts) > 0, "Should have non-empty dynamic contexts"
        test_contexts = [c for c in contexts if 'test' in c.lower()]
        assert len(test_contexts) > 0, (
            f"Should have test-function contexts, got: {contexts[:5]}"
        )

    def test_has_source_files(self):
        conn = sqlite3.connect('/app/.coverage')
        try:
            rows = conn.execute("SELECT path FROM file").fetchall()
        finally:
            conn.close()
        paths = [r[0] for r in rows]
        engine_found = any('engine.py' in p for p in paths)
        evaluator_found = any('evaluator.py' in p for p in paths)
        assert engine_found, f"engine.py should be in coverage data. Files: {paths}"
        assert evaluator_found, f"evaluator.py should be in coverage data. Files: {paths}"

    def test_context_count(self):
        """We have ~40 test functions; each should produce a context."""
        conn = sqlite3.connect('/app/.coverage')
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM context WHERE context != ''"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count >= 20, (
            f"Expected >=20 test contexts from the test suite, got {count}"
        )


# ---------------------------------------------------------------------------
# 3. Verify analysis result files
# ---------------------------------------------------------------------------

class TestTestFileMap:
    """Verify /app/results/test_file_map.json is correct."""

    @pytest.fixture(autouse=True)
    def _load_data(self):
        path = '/app/results/test_file_map.json'
        assert os.path.exists(path), f"{path} must exist"
        with open(path) as f:
            self.data = json.load(f)

    def test_is_dict(self):
        assert isinstance(self.data, dict), "test_file_map should be a JSON object"

    def test_not_empty(self):
        assert len(self.data) > 0, "test_file_map should not be empty"

    def test_all_contexts_are_tests(self):
        for context in self.data:
            assert 'test' in context.lower(), (
                f"Context should be a test function name: {context!r}"
            )

    def test_values_are_file_lists(self):
        for context, files in self.data.items():
            assert isinstance(files, list), f"Value for {context!r} should be a list"
            for f in files:
                assert isinstance(f, str), f"File entry should be a string: {f!r}"

    def test_covers_engine(self):
        all_files = set()
        for files in self.data.values():
            all_files.update(files)
        assert any('engine.py' in f for f in all_files), (
            f"engine.py should be covered. All files: {all_files}"
        )

    def test_covers_evaluator(self):
        all_files = set()
        for files in self.data.values():
            all_files.update(files)
        assert any('evaluator.py' in f for f in all_files), (
            f"evaluator.py should be covered. All files: {all_files}"
        )

    def test_has_enough_contexts(self):
        assert len(self.data) >= 20, (
            f"Should have at least 20 test contexts, got {len(self.data)}"
        )

    def test_no_empty_context(self):
        assert '' not in self.data, "Empty context should be excluded"


class TestFragileLines:
    """Verify /app/results/fragile_lines.json is correct."""

    @pytest.fixture(autouse=True)
    def _load_data(self):
        path = '/app/results/fragile_lines.json'
        assert os.path.exists(path), f"{path} must exist"
        with open(path) as f:
            self.data = json.load(f)

    def test_is_dict(self):
        assert isinstance(self.data, dict), "fragile_lines should be a JSON object"

    def test_not_empty(self):
        assert len(self.data) > 0, "fragile_lines should not be empty"

    def test_has_engine(self):
        assert any('engine.py' in p for p in self.data), (
            "Should have fragile lines for engine.py"
        )

    def test_has_evaluator(self):
        assert any('evaluator.py' in p for p in self.data), (
            "Should have fragile lines for evaluator.py"
        )

    def test_values_are_sorted_int_lists(self):
        for path, lines in self.data.items():
            assert isinstance(lines, list), f"Lines for {path} should be a list"
            assert all(isinstance(l, int) for l in lines), (
                f"All entries should be ints: {lines[:5]}"
            )
            assert lines == sorted(lines), f"Lines should be sorted for {path}"
            assert len(lines) == len(set(lines)), (
                f"Lines should be deduplicated for {path}"
            )

    def test_fragile_lines_exist(self):
        for path, lines in self.data.items():
            assert len(lines) > 0, f"Should have some fragile lines for {path}"

    def test_fragile_lines_not_all(self):
        """Fragile lines should be a subset, not every line."""
        conn = sqlite3.connect('/app/.coverage')
        try:
            for path, fragile in self.data.items():
                # Get total unique lines covered for this file
                rows = conn.execute(
                    "SELECT COUNT(DISTINCT a.fromno) FROM arc a "
                    "JOIN file f ON a.file_id = f.id "
                    "JOIN context c ON a.context_id = c.id "
                    "WHERE f.path = ? AND c.context != '' AND a.fromno > 0",
                    (path,),
                ).fetchone()
                if rows and rows[0] > 0:
                    total = rows[0]
                    assert len(fragile) < total, (
                        f"Fragile lines ({len(fragile)}) should be fewer than "
                        f"total covered lines ({total}) for {path}"
                    )
        finally:
            conn.close()

#!/usr/bin/env python3
"""Programmatically fix all CI pipeline issues in the logminer project.

"""
import re
import sys
import os


def read_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def apply_fix(path: str, old: str, new: str, description: str) -> None:
    content = read_file(path)
    if old not in content:
        print(f"WARNING: pattern not found for fix: {description}", file=sys.stderr)
        print(f"  File: {path}", file=sys.stderr)
        print(f"  Pattern: {old[:80]}...", file=sys.stderr)
        return
    content = content.replace(old, new, 1)
    write_file(path, content)
    print(f"FIXED: {description}")


# ============================================================
# CONFIG FILE PRECEDENCE FIXES
# ============================================================

# Fix A: Remove ruff.toml — it overrides pyproject.toml's [tool.ruff]
# section with a reduced rule set (select=["E","W"]) that omits pyflakes (F)
# and isort (I) rules, silently hiding unused import violations.
# The correct config is in pyproject.toml with select=["E","F","W","I"].
if os.path.exists('/app/ruff.toml'):
    os.remove('/app/ruff.toml')
    print("FIXED: removed ruff.toml (pyproject.toml has correct ruff config)")

# Fix B: Remove mypy.ini — it overrides pyproject.toml's [tool.mypy] section
# with lax settings (disallow_untyped_defs=False, check_untyped_defs=False).
# mypy's config resolution: mypy.ini > setup.cfg > pyproject.toml, so even
# after removing --config-file=setup.cfg from the Makefile, mypy would use
# mypy.ini instead of pyproject.toml's strict settings.
if os.path.exists('/app/mypy.ini'):
    os.remove('/app/mypy.ini')
    print("FIXED: removed mypy.ini (pyproject.toml has correct mypy config)")

# ============================================================
# BUILD CONFIGURATION FIXES
# ============================================================

# Fix C: Makefile — wrong Python binary (python3.11 does not exist)
apply_fix(
    '/app/Makefile',
    'PYTHON ?= python3.11',
    'PYTHON ?= python3',
    'Makefile: python3.11 -> python3',
)

# Fix D: Makefile — references setup.cfg for mypy config, but setup.cfg
# has wrong settings (follow_imports=skip, disallow_untyped_defs=False).
# The correct config is in pyproject.toml. Remove the --config-file flag
# so mypy uses pyproject.toml automatically (after mypy.ini is removed).
apply_fix(
    '/app/Makefile',
    '--config-file=setup.cfg ',
    '',
    'Makefile: remove --config-file=setup.cfg (use pyproject.toml instead)',
)

# Fix E: GitHub Actions workflow — working-directory references ./logminer
# which does not exist. The repo root IS the project root.
content = read_file('/app/.github/workflows/ci.yml')
content = content.replace('working-directory: ./logminer', 'working-directory: .')
write_file('/app/.github/workflows/ci.yml', content)
print("FIXED: ci.yml: working-directory ./logminer -> .")

# ============================================================
# PYTHON SOURCE CODE FIXES
# ============================================================

# Fix 1: pyproject.toml — wrong pyyaml version constraint
# PyYAML 7.0 does not exist; latest is 6.0.x
apply_fix(
    '/app/pyproject.toml',
    '"pyyaml>=7.0"',
    '"pyyaml>=6.0"',
    'pyproject.toml: pyyaml>=7.0 -> pyyaml>=6.0',
)

# Fix 2: parser.py — remove unused import (F401)
# typing.OrderedDict is imported but never used
apply_fix(
    '/app/src/logminer/parser.py',
    'from typing import Dict, List, Optional, OrderedDict',
    'from typing import Dict, List, Optional',
    'parser.py: remove unused OrderedDict import',
)

# Fix 3: parser.py — fix ANSI escape code regex
# Current regex \x1b\[\d+m only handles simple codes like \x1b[31m
# but not extended codes like \x1b[38;5;196m or \x1b[0;1;31m
apply_fix(
    '/app/src/logminer/parser.py',
    r"r'\x1b\[\d+m'",
    r"r'\x1b\[[\d;]*m'",
    'parser.py: fix ANSI regex for extended escape sequences',
)

# Fix 4: localizer.py — fix return type annotation on rank_candidates
# Annotation says list[dict[str, Any]] but method returns list[tuple]
apply_fix(
    '/app/src/logminer/localizer.py',
    ') -> list[dict[str, Any]]:',
    ') -> List[Tuple[str, float, int]]:',
    'localizer.py: fix rank_candidates return type annotation',
)

# Fix 4b: localizer.py — remove now-unused Any import
# After fixing the return type, Any is no longer used anywhere
apply_fix(
    '/app/src/logminer/localizer.py',
    'from typing import Any, Dict, List, Optional, Tuple',
    'from typing import Dict, List, Optional, Tuple',
    'localizer.py: remove unused Any import after type annotation fix',
)

# Fix 5: localizer.py — fix find_enclosing_node to use containment
# Uses intersection (node.start <= line_end and line_start <= node.end)
# instead of strict containment (node.start <= line_start and line_end <= node.end)
apply_fix(
    '/app/src/logminer/localizer.py',
    'if node.start <= line_end and line_start <= node.end:  # intersection',
    'if node.start <= line_start and line_end <= node.end:  # strict containment',
    'localizer.py: fix find_enclosing_node intersection -> containment',
)

# Fix 6: localizer.py — fix BM25 IDF formula
# log((n-df)/(df+eps)) produces math domain error when df==n (log(0))
# Standard BM25 IDF: log(1 + (n - df + 0.5) / (df + 0.5))
apply_fix(
    '/app/src/logminer/localizer.py',
    'return math.log((self._n_docs - df) / (df + 1e-10))',
    'return math.log(1 + (self._n_docs - df + 0.5) / (df + 0.5))',
    'localizer.py: fix BM25 IDF to avoid math domain error',
)

# Fix 7: chunker.py — guard against infinite loop
# When overlap >= chunk_size, step = chunk_size - overlap <= 0,
# causing pos to never advance
apply_fix(
    '/app/src/logminer/chunker.py',
    '    step = chunk_size - overlap\n',
    '    step = chunk_size - overlap\n    if step <= 0:\n        step = max(1, chunk_size // 2)\n',
    'chunker.py: add guard for overlap >= chunk_size',
)

# Fix 8: reporter.py — fix key typo
# 'error_summry' should be 'error_summary'
apply_fix(
    '/app/src/logminer/reporter.py',
    "'error_summry'",
    "'error_summary'",
    "reporter.py: fix key typo 'error_summry' -> 'error_summary'",
)

# ============================================================
# TEST QUARANTINE FIXES
# ============================================================

# Fix 9: test_parser.py — unskip test_parse_log_with_colored_output
# This test was incorrectly marked as "flaky" — the intermittent failure
# was caused by the ANSI regex bug (Fix 3). With the regex fixed, this
# test passes reliably. Remove the skip decorator and the now-unused
# pytest import.
apply_fix(
    '/app/tests/test_parser.py',
    '"""Tests for logminer.parser module."""\nimport pytest\n',
    '"""Tests for logminer.parser module."""\n',
    'test_parser.py: remove unused pytest import',
)

apply_fix(
    '/app/tests/test_parser.py',
    '@pytest.mark.skip("TODO: flaky on CI, ANSI parsing intermittently fails — see issue #47")\n',
    '',
    'test_parser.py: unskip test_parse_log_with_colored_output',
)

# Fix 10: test_localizer.py — remove xfail from test_bm25_common_term_scoring
# This test was marked @pytest.mark.xfail(strict=True) under the assumption
# that BM25 IDF produces negative scores for ubiquitous terms. After fixing
# the IDF formula (Fix 6) to the standard BM25 formulation, the IDF for
# ubiquitous terms is non-negative (log(1+(n-df+0.5)/(df+0.5)) >= 0),
# making the test pass. With strict=True, the unexpected pass causes a
# test failure. The xfail must be removed because the original assumption
# was incorrect — the "known limitation" was actually a bug.
apply_fix(
    '/app/tests/test_localizer.py',
    '"""Tests for logminer.localizer module."""\nimport pytest\n',
    '"""Tests for logminer.localizer module."""\n',
    'test_localizer.py: remove unused pytest import',
)

apply_fix(
    '/app/tests/test_localizer.py',
    '@pytest.mark.xfail(\n'
    '    reason="BM25 scorer produces negative relevance for ubiquitous terms — known limitation",\n'
    '    strict=True,\n'
    ')\n',
    '',
    'test_localizer.py: remove xfail from test_bm25_common_term_scoring',
)

print("\nAll fixes applied.")

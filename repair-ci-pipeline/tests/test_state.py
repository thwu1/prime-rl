"""Verifier tests: all CI stages, build configuration, tool configs, and workflow must pass.

"""
import subprocess
import os
import re
import tempfile


def _run(cmd, timeout=120, cwd=None):
    """Run a command and return the CompletedProcess."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
    )


def test_pip_install():
    """Stage 1: Package dependencies resolve and install succeeds."""
    r = _run(["pip3", "install", "-e", "/app/"])
    assert r.returncode == 0, (
        f"pip install -e /app/ failed (exit {r.returncode}):\n"
        f"STDOUT:\n{r.stdout[-2000:]}\n"
        f"STDERR:\n{r.stderr[-2000:]}"
    )


def test_ruff_check():
    """Stage 2: Source code passes ruff linting with no errors."""
    _run(["pip3", "install", "-e", "/app/"])
    r = _run(["ruff", "check", "/app/src/"], timeout=60)
    assert r.returncode == 0, (
        f"ruff check failed (exit {r.returncode}):\n"
        f"{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    )


def test_ruff_lint_rules():
    """Ruff config must check for unused imports (F) and import ordering (I).

    This verifies that no competing config file (e.g. ruff.toml) silently
    overrides pyproject.toml's lint rule selection with a reduced set.
    """
    test_code = "import os\n\nx = 1\n"
    fd, temp_path = tempfile.mkstemp(suffix='.py', dir='/app/src/logminer/')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(test_code)
        r = _run(["ruff", "check", temp_path], cwd="/app")
        assert r.returncode != 0, (
            "Ruff must detect unused imports (F401) but accepted a file with "
            "'import os' unused — check for config files (ruff.toml) that may "
            "exclude pyflakes (F) or isort (I) rules"
        )
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_mypy_check():
    """Stage 3: Source code passes mypy type checking."""
    _run(["pip3", "install", "-e", "/app/"])
    r = _run(["mypy", "src/logminer/"], timeout=60, cwd="/app")
    assert r.returncode == 0, (
        f"mypy check failed (exit {r.returncode}):\n"
        f"{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    )


def test_mypy_enforces_strict_typing():
    """Mypy config must enforce disallow_untyped_defs as set in pyproject.toml.

    This verifies that no competing config file (e.g. mypy.ini, setup.cfg)
    silently overrides pyproject.toml's strict type-checking settings.
    Mypy resolves config from CWD, so we run from /app/ to pick up the
    project's config files.
    """
    test_code = "def untyped_func(x):\n    return x + 1\n"
    fd, temp_path = tempfile.mkstemp(
        suffix='.py', dir='/tmp/', prefix='_mypy_canary_'
    )
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(test_code)
        r = _run(
            ["mypy", temp_path],
            cwd="/app",
        )
        assert r.returncode != 0, (
            "mypy must enforce disallow_untyped_defs (reject functions without "
            "type annotations) but accepted an untyped function — check for "
            "config files (mypy.ini, setup.cfg) overriding pyproject.toml's "
            "strict settings"
        )
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_project_tests():
    """Stage 4: All project tests pass."""
    _run(["pip3", "install", "-e", "/app/"])
    r = _run(["pytest", "/app/tests/", "-v", "--tb=short"], timeout=120)
    assert r.returncode == 0, (
        f"Project tests failed (exit {r.returncode}):\n"
        f"{r.stdout[-3000:]}\n{r.stderr[-2000:]}"
    )


def test_no_quarantined_tests():
    """All tests must run normally — no skipped, xfail, or xpassed markers.

    Tests that were quarantined (skipped or xfail) due to bugs should be
    restored once the underlying issues are fixed.
    """
    _run(["pip3", "install", "-e", "/app/"])
    r = _run(["pytest", "/app/tests/", "-v"], timeout=120)
    assert r.returncode == 0, (
        f"Tests failed (exit {r.returncode}):\n{r.stdout[-2000:]}"
    )
    for pattern, label in [
        (r'(\d+) skipped', 'skipped'),
        (r'(\d+) xfailed', 'xfailed'),
        (r'(\d+) xpassed', 'xpassed'),
    ]:
        match = re.search(pattern, r.stdout)
        if match:
            count = int(match.group(1))
            assert count == 0, (
                f"{count} test(s) {label} — all quarantine markers (skip/xfail) "
                f"should be removed after fixing the underlying issues:\n"
                f"{r.stdout[-2000:]}"
            )


def test_make_ci():
    """Full CI pipeline via 'make ci' must succeed end-to-end."""
    _run(["pip3", "install", "-e", "/app/"])
    r = _run(["make", "ci"], timeout=180, cwd="/app")
    assert r.returncode == 0, (
        f"make ci failed (exit {r.returncode}):\n"
        f"STDOUT:\n{r.stdout[-3000:]}\n"
        f"STDERR:\n{r.stderr[-3000:]}"
    )


def test_workflow_yaml():
    """GitHub Actions workflow is valid YAML with correct project paths."""
    import yaml

    ci_path = '/app/.github/workflows/ci.yml'
    assert os.path.exists(ci_path), "CI workflow file missing"

    with open(ci_path) as f:
        workflow = yaml.safe_load(f)

    assert isinstance(workflow, dict), "Workflow file is not valid YAML"
    assert 'jobs' in workflow, "Workflow must define jobs"

    for job_name, job in workflow['jobs'].items():
        steps = job.get('steps', [])
        for step in steps:
            wd = step.get('working-directory', '.')
            if wd and wd != '.':
                normalized = os.path.normpath(wd)
                if normalized != '.' and not normalized.startswith('/'):
                    full_path = os.path.join('/app', normalized)
                    assert os.path.isdir(full_path), (
                        f"Job '{job_name}', step '{step.get('name', '')}': "
                        f"working-directory '{wd}' does not exist in the project"
                    )

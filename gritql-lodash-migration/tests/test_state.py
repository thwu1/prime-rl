"""Tests for the GritQL lodash-to-native migration pattern.

Validates that the pattern:
1. Passes all inline grit pattern tests (call transformations)
2. Correctly removes ES6/CommonJS lodash imports when all calls are transformed
3. Preserves imports when untransformable lodash calls remain

"""
import os
import re
import subprocess


GRIT = "grit"


def _run_grit(args, cwd="/app", timeout=120):
    env = os.environ.copy()
    env["PATH"] = "/usr/local/bin:" + env.get("PATH", "")
    return subprocess.run(
        [GRIT] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        env=env,
    )


def _apply_to_file(filename, code):
    """Write code to a JS file inside /app, apply the pattern, return result."""
    filepath = os.path.join("/app", filename)
    try:
        with open(filepath, "w") as f:
            f.write(code)
        _run_grit(["apply", "lodash_to_native", filepath])
        with open(filepath) as f:
            return f.read()
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


# ── Pattern structure tests ──────────────────────────────────


def test_pattern_file_has_body():
    """Pattern file must contain a real GritQL body, not the placeholder."""
    with open("/app/.grit/patterns/lodash_to_native.md") as f:
        content = f.read()
    assert "engine marzano(0.1)" in content
    assert "language js" in content
    assert "placeholder_that_matches_nothing" not in content, (
        "Pattern body still contains the placeholder"
    )


# ── Inline tests ──────────────────────────────────────────────


def test_grit_patterns_test():
    """All inline test sections across pattern files must pass."""
    result = _run_grit(["patterns", "test"])
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"grit patterns test failed (exit {result.returncode}):\n{combined}"
    )
    # Verify that inline test cases actually exist and pass (at least 7 samples)
    match = re.search(r"All (\d+) samples passed", combined)
    assert match, (
        f"Could not find passing samples count in output:\n{combined}"
    )
    n_samples = int(match.group(1))
    assert n_samples >= 7, (
        f"Expected at least 7 passing inline test samples, got {n_samples}"
    )


# ── Import / require removal ─────────────────────────────────


def test_es6_import_removal():
    """ES6 default import removed when all _.* calls are transformed."""
    code = (
        "import _ from 'lodash';\n"
        "const k = _.keys(obj);\n"
        "const v = _.values(obj);\n"
    )
    result = _apply_to_file("_tbench_es6.js", code)
    assert "import" not in result, (
        f"ES6 import should be removed when all calls are replaced:\n{result}"
    )
    assert "Object.keys(obj)" in result
    assert "Object.values(obj)" in result


def test_commonjs_require_removal():
    """CommonJS require removed when all _.* calls are transformed."""
    code = (
        "const _ = require('lodash');\n"
        "const k = _.keys(obj);\n"
    )
    result = _apply_to_file("_tbench_cjs.js", code)
    assert "require" not in result, (
        f"require should be removed when all calls are replaced:\n{result}"
    )
    assert "Object.keys(obj)" in result


def test_partial_migration_preserves_import():
    """Import preserved when untransformable _.* calls remain."""
    code = (
        "import _ from 'lodash';\n"
        "const k = _.keys(obj);\n"
        "const d = _.debounce(fn, 300);\n"
    )
    result = _apply_to_file("_tbench_partial.js", code)
    has_import = "import" in result or "require" in result
    assert has_import, (
        f"Import must stay when untransformable calls like _.debounce remain:\n{result}"
    )
    assert "Object.keys(obj)" in result, (
        f"_.keys should still be transformed:\n{result}"
    )
    assert "_.debounce" in result, (
        f"_.debounce must NOT be transformed:\n{result}"
    )


# ── Complex / mixed ──────────────────────────────────────────


def test_complex_mixed_transformation():
    """Multiple different lodash calls in one file all transformed correctly."""
    code = (
        "import _ from 'lodash';\n"
        "const names = _.map(users, u => u.name);\n"
        "const active = _.filter(items, i => i.active);\n"
        "const unique = _.uniq(names);\n"
        "const flat = _.flatten(nested);\n"
        "const k = _.keys(config);\n"
        "if (_.isArray(data)) { console.log('yes'); }\n"
        "const copy = _.cloneDeep(original);\n"
    )
    result = _apply_to_file("_tbench_mixed.js", code)

    assert "users.map(" in result, f"_.map not transformed:\n{result}"
    assert "items.filter(" in result, f"_.filter not transformed:\n{result}"
    assert "[...new Set(names)]" in result, f"_.uniq not transformed:\n{result}"
    assert "nested.flat()" in result, f"_.flatten not transformed:\n{result}"
    assert "Object.keys(config)" in result, f"_.keys not transformed:\n{result}"
    assert "Array.isArray(data)" in result, f"_.isArray not transformed:\n{result}"
    assert "structuredClone(original)" in result, f"_.cloneDeep not transformed:\n{result}"
    assert "import" not in result, (
        f"Import should be removed (all calls replaced):\n{result}"
    )


import subprocess
import json
import os
import glob
import re
import tempfile


# ---- Results JSON existence and schema ----

def test_results_json_exists():
    assert os.path.isfile('/app/results.json'), "results.json not found"


def test_results_json_valid():
    with open('/app/results.json') as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json root must be a dict"


def test_results_has_total_tests():
    with open('/app/results.json') as f:
        data = json.load(f)
    assert isinstance(data.get('total_tests'), int)
    assert data['total_tests'] >= 50, \
        f"total_tests={data['total_tests']}, need >=50"


def test_results_has_categories():
    with open('/app/results.json') as f:
        data = json.load(f)
    assert isinstance(data.get('categories'), dict)


def test_results_has_discrepancies():
    with open('/app/results.json') as f:
        data = json.load(f)
    assert isinstance(data.get('discrepancies'), list)


def test_all_categories_present():
    with open('/app/results.json') as f:
        data = json.load(f)
    required = {'irr_flow', 'alias', 'volatile_opt', 'int_promo', 'call_conv'}
    actual = set(data['categories'].keys())
    missing = required - actual
    assert not missing, f"Missing categories: {missing}"


def test_category_minimum_counts():
    with open('/app/results.json') as f:
        data = json.load(f)
    for cat_name in ['irr_flow', 'alias', 'volatile_opt', 'int_promo', 'call_conv']:
        cat_data = data['categories'][cat_name]
        count = cat_data.get('count', 0)
        assert count >= 10, \
            f"Category {cat_name} has {count} tests, need >=10"


def test_category_counts_consistent():
    with open('/app/results.json') as f:
        data = json.load(f)
    cat_total = sum(c.get('count', 0) for c in data['categories'].values())
    assert cat_total == data['total_tests'], \
        f"Sum of category counts ({cat_total}) != total_tests ({data['total_tests']})"


# ---- Dual compiler verification ----

def test_results_mentions_both_compilers():
    """results.json must include data from both gcc and clang."""
    with open('/app/results.json') as f:
        content = f.read()
    content_lower = content.lower()
    assert 'gcc' in content_lower, \
        "results.json does not mention gcc"
    assert 'clang' in content_lower, \
        "results.json does not mention clang"


def test_compilers_tested_field():
    """compilers_tested must list both gcc and clang."""
    with open('/app/results.json') as f:
        data = json.load(f)
    compilers = data.get('compilers_tested', [])
    compilers_lower = [c.lower() for c in compilers]
    assert 'gcc' in compilers_lower, \
        f"compilers_tested {compilers} does not include gcc"
    assert 'clang' in compilers_lower, \
        f"compilers_tested {compilers} does not include clang"


# ---- Test file existence ----

def test_irr_flow_files_exist():
    files = glob.glob('/app/tests/irr_flow/*.c')
    assert len(files) >= 10, f"irr_flow has {len(files)} .c files, need >=10"


def test_alias_files_exist():
    files = glob.glob('/app/tests/alias/*.c')
    assert len(files) >= 10, f"alias has {len(files)} .c files, need >=10"


def test_volatile_opt_files_exist():
    files = glob.glob('/app/tests/volatile_opt/*.c')
    assert len(files) >= 10, f"volatile_opt has {len(files)} .c files, need >=10"


def test_int_promo_files_exist():
    files = glob.glob('/app/tests/int_promo/*.c')
    assert len(files) >= 10, f"int_promo has {len(files)} .c files, need >=10"


def test_call_conv_has_paired_files():
    cat_dir = '/app/tests/call_conv'
    assert os.path.isdir(cat_dir), "call_conv directory missing"
    callee_files = sorted(glob.glob(os.path.join(cat_dir, '*_callee.c')))
    caller_files = sorted(glob.glob(os.path.join(cat_dir, '*_caller.c')))
    assert len(callee_files) >= 10, \
        f"call_conv has {len(callee_files)} callee files, need >=10"
    assert len(caller_files) >= 10, \
        f"call_conv has {len(caller_files)} caller files, need >=10"
    for cf in callee_files:
        prefix = cf.replace('_callee.c', '')
        caller = prefix + '_caller.c'
        assert os.path.exists(caller), f"Missing caller for {cf}"


# ---- Content pattern checks ----

def test_irr_flow_has_gotos():
    """Every irr_flow test must use goto."""
    files = glob.glob('/app/tests/irr_flow/*.c')
    for f in files:
        with open(f) as fh:
            content = fh.read()
        assert 'goto' in content, f"{f} missing goto"


def test_irr_flow_is_irreducible():
    """At least half of irr_flow tests have genuine irreducible patterns."""
    files = glob.glob('/app/tests/irr_flow/*.c')
    irreducible_count = 0
    for f in files:
        with open(f) as fh:
            content = fh.read()
        labels = set(re.findall(r'\b(\w+)\s*:', content))
        goto_targets = set(re.findall(r'goto\s+(\w+)', content))
        if len(goto_targets & labels) >= 2:
            irreducible_count += 1
    assert irreducible_count >= 5, \
        f"Only {irreducible_count} irr_flow tests have irreducible patterns (>=5 needed)"


def test_alias_has_pointer_ops():
    """Alias tests must use pointer dereference."""
    files = glob.glob('/app/tests/alias/*.c')
    for f in files:
        with open(f) as fh:
            content = fh.read()
        has_ptrs = ('*' in content and
                    ('&' in content or 'int *' in content or 'int*' in content
                     or 'char *' in content or 'void *' in content))
        assert has_ptrs, f"{f} missing pointer operations"


def test_volatile_opt_uses_volatile():
    """Volatile tests must use volatile keyword."""
    files = glob.glob('/app/tests/volatile_opt/*.c')
    for f in files:
        with open(f) as fh:
            content = fh.read()
        assert 'volatile' in content, f"{f} missing volatile keyword"


def test_int_promo_uses_mixed_types():
    """Integer promotion tests use at least 2 different type widths."""
    files = glob.glob('/app/tests/int_promo/*.c')
    mixed_count = 0
    for f in files:
        with open(f) as fh:
            content = fh.read()
        type_keywords = ['unsigned', 'short', 'long', 'char', 'uint',
                         'int8', 'int16', 'int32', 'int64', 'size_t']
        matches = sum(1 for t in type_keywords if t in content)
        if matches >= 2:
            mixed_count += 1
    assert mixed_count >= 5, \
        f"Only {mixed_count} int_promo tests use mixed types (>=5 needed)"


# ---- Independent compilation and execution checks ----

def _compile_and_run(c_file, opt_level, compiler='gcc'):
    """Compile a single C file and run it."""
    with tempfile.NamedTemporaryFile(suffix='', delete=False) as f:
        binary = f.name
    try:
        comp = subprocess.run(
            [compiler, opt_level, '-o', binary, c_file, '-lm', '-w'],
            capture_output=True, text=True, timeout=30
        )
        if comp.returncode != 0:
            return False, comp.returncode, comp.stderr
        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
        return True, run.returncode, run.stdout
    except Exception as e:
        return False, -1, str(e)
    finally:
        if os.path.exists(binary):
            os.unlink(binary)


def _compile_separate_and_run(caller, callee, opt_level, compiler='gcc'):
    """Compile caller/callee separately, link, and run."""
    with tempfile.NamedTemporaryFile(suffix='', delete=False) as f:
        binary = f.name
    callee_o = binary + '_callee.o'
    caller_o = binary + '_caller.o'
    try:
        c1 = subprocess.run(
            [compiler, opt_level, '-c', callee, '-o', callee_o, '-w'],
            capture_output=True, text=True, timeout=30
        )
        if c1.returncode != 0:
            return False, c1.returncode, c1.stderr
        c2 = subprocess.run(
            [compiler, opt_level, '-c', caller, '-o', caller_o, '-w'],
            capture_output=True, text=True, timeout=30
        )
        if c2.returncode != 0:
            return False, c2.returncode, c2.stderr
        link = subprocess.run(
            [compiler, callee_o, caller_o, '-o', binary, '-lm', '-w'],
            capture_output=True, text=True, timeout=30
        )
        if link.returncode != 0:
            return False, link.returncode, link.stderr
        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
        return True, run.returncode, run.stdout
    except Exception as e:
        return False, -1, str(e)
    finally:
        for p in [binary, callee_o, caller_o]:
            if os.path.exists(p):
                os.unlink(p)


# -- GCC at -O0 --

def test_irr_flow_gcc_O0():
    """All irr_flow tests compile and pass at -O0 with gcc."""
    files = sorted(glob.glob('/app/tests/irr_flow/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'gcc')
        assert ok, f"gcc -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"gcc -O0 fail: {f} exit={exit_code}"


def test_alias_gcc_O0():
    files = sorted(glob.glob('/app/tests/alias/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'gcc')
        assert ok, f"gcc -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"gcc -O0 fail: {f} exit={exit_code}"


def test_volatile_gcc_O0():
    files = sorted(glob.glob('/app/tests/volatile_opt/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'gcc')
        assert ok, f"gcc -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"gcc -O0 fail: {f} exit={exit_code}"


def test_int_promo_gcc_O0():
    files = sorted(glob.glob('/app/tests/int_promo/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'gcc')
        assert ok, f"gcc -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"gcc -O0 fail: {f} exit={exit_code}"


def test_call_conv_gcc_O0():
    cat_dir = '/app/tests/call_conv'
    callers = sorted(glob.glob(os.path.join(cat_dir, '*_caller.c')))
    assert len(callers) >= 10
    for caller in callers:
        prefix = caller.replace('_caller.c', '')
        callee = prefix + '_callee.c'
        assert os.path.exists(callee), f"Missing callee for {caller}"
        ok, exit_code, msg = _compile_separate_and_run(
            caller, callee, '-O0', 'gcc'
        )
        assert ok, f"gcc -O0 compile/link failed: {caller}: {msg}"
        assert exit_code == 0, f"gcc -O0 fail: {caller} exit={exit_code}"


# -- Clang at -O0 --

def test_irr_flow_clang_O0():
    """All irr_flow tests compile and pass at -O0 with clang."""
    files = sorted(glob.glob('/app/tests/irr_flow/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'clang')
        assert ok, f"clang -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"clang -O0 fail: {f} exit={exit_code}"


def test_alias_clang_O0():
    files = sorted(glob.glob('/app/tests/alias/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'clang')
        assert ok, f"clang -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"clang -O0 fail: {f} exit={exit_code}"


def test_volatile_clang_O0():
    files = sorted(glob.glob('/app/tests/volatile_opt/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'clang')
        assert ok, f"clang -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"clang -O0 fail: {f} exit={exit_code}"


def test_int_promo_clang_O0():
    files = sorted(glob.glob('/app/tests/int_promo/*.c'))
    assert len(files) >= 10
    for f in files:
        ok, exit_code, msg = _compile_and_run(f, '-O0', 'clang')
        assert ok, f"clang -O0 compile failed: {f}: {msg}"
        assert exit_code == 0, f"clang -O0 fail: {f} exit={exit_code}"


def test_call_conv_clang_O0():
    cat_dir = '/app/tests/call_conv'
    callers = sorted(glob.glob(os.path.join(cat_dir, '*_caller.c')))
    assert len(callers) >= 10
    for caller in callers:
        prefix = caller.replace('_caller.c', '')
        callee = prefix + '_callee.c'
        assert os.path.exists(callee)
        ok, exit_code, msg = _compile_separate_and_run(
            caller, callee, '-O0', 'clang'
        )
        assert ok, f"clang -O0 compile/link failed: {caller}: {msg}"
        assert exit_code == 0, f"clang -O0 fail: {caller} exit={exit_code}"

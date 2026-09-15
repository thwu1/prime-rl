"""
Tests for the safe math cross-compiler differential testing framework.

Verifies that:
1. Safe math wrappers handle all UB edge cases under both gcc and clang
2. The expression generator itself is UBSan-clean
3. Generated programs produce consistent checksums across gcc/clang at O0/O2
4. No undefined behavior sanitizer violations in generated programs
5. gcov coverage of safe_math.h is adequate
6. make coverage target functions correctly

"""

import subprocess
import os
import re
import shutil
import glob
import pytest


def _compile(sources, output, compiler='gcc', extra_flags=None):
    """Compile C source file(s) with optional extra flags."""
    cmd = [compiler, '-std=c11', '-I/app']
    if extra_flags:
        cmd.extend(extra_flags)
    if isinstance(sources, str):
        sources = [sources]
    cmd.extend(sources)
    cmd.extend(['-o', output])
    return subprocess.run(cmd, capture_output=True, text=True)


def _run(exe, timeout=30):
    """Run a compiled executable."""
    return subprocess.run([exe], capture_output=True, text=True, timeout=timeout)


def _build_expr_gen():
    """Ensure expr_gen is built."""
    r = subprocess.run(['make', '-C', '/app', 'expr_gen'],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Failed to build expr_gen:\n{r.stderr}"


def _generate_program(seed):
    """Generate a test program for the given seed, return path."""
    r = subprocess.run(['/app/expr_gen', str(seed)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"expr_gen failed for seed {seed}"
    path = f'/tmp/tbench_gen_{seed}.c'
    with open(path, 'w') as f:
        f.write(r.stdout)
    return path


class TestEdgeCasesUBSan:
    """Test safe_math edge cases compiled with UBSan under both gcc and clang."""

    @pytest.mark.parametrize("compiler", ["gcc", "clang"])
    @pytest.mark.parametrize("opt", ["-O0", "-O2"])
    def test_no_ubsan_violations(self, compiler, opt):
        tag = f'{compiler}_{opt.replace("-", "")}'
        exe = f'/tmp/test_edge_{tag}'
        r = _compile('/tests/test_edge_cases.c', exe,
                     compiler=compiler,
                     extra_flags=[opt, '-fsanitize=undefined',
                                  '-fno-sanitize-recover=all'])
        assert r.returncode == 0, \
            f"Compilation with {compiler} {opt} failed:\n{r.stderr}"
        r = _run(exe)
        assert 'runtime error' not in r.stderr, \
            f"UBSan violation with {compiler} {opt}:\n{r.stderr}"
        assert r.returncode == 0, \
            f"Edge case tests failed with {compiler} {opt}:\n{r.stdout}\n{r.stderr}"


class TestExprGenUBSan:
    """The expression generator itself must be UBSan-clean."""

    NUM_SEEDS = 50

    def test_build_with_ubsan(self):
        r = _compile('/app/expr_gen.c', '/tmp/expr_gen_ubsan',
                     extra_flags=['-O0', '-fsanitize=undefined',
                                  '-fno-sanitize-recover=all'])
        assert r.returncode == 0, f"UBSan build failed:\n{r.stderr}"

    def test_no_violations_across_seeds(self):
        r = _compile('/app/expr_gen.c', '/tmp/expr_gen_ubsan',
                     extra_flags=['-O0', '-fsanitize=undefined',
                                  '-fno-sanitize-recover=all'])
        assert r.returncode == 0, f"UBSan build failed:\n{r.stderr}"
        violations = []
        for seed in range(1, self.NUM_SEEDS + 1):
            r = subprocess.run(['/tmp/expr_gen_ubsan', str(seed)],
                               capture_output=True, text=True, timeout=10)
            if 'runtime error' in r.stderr:
                err = [l for l in r.stderr.split('\n')
                       if 'runtime error' in l]
                violations.append(
                    (seed, err[0][:200] if err else r.stderr[:200]))
        assert len(violations) == 0, \
            f"expr_gen UBSan violations in {len(violations)}/{self.NUM_SEEDS} seeds:\n" + \
            "\n".join(f"  seed {s}: {err}" for s, err in violations[:5])


class TestCrossCompilerDifferential:
    """Generated programs must produce identical checksums across gcc/clang at O0/O2."""

    NUM_SEEDS = 50
    CONFIGS = [('gcc', '-O0'), ('gcc', '-O2'),
               ('clang', '-O0'), ('clang', '-O2')]

    def test_checksums_match(self):
        _build_expr_gen()
        mismatches = []

        for seed in range(1, self.NUM_SEEDS + 1):
            prog_path = _generate_program(seed)
            outputs = {}
            compile_fail = False

            for compiler, opt in self.CONFIGS:
                tag = f'{compiler}_{opt.replace("-", "")}'
                exe = f'/tmp/tbench_diff_{seed}_{tag}'
                r = _compile(prog_path, exe, compiler=compiler,
                             extra_flags=[opt])
                if r.returncode != 0:
                    mismatches.append(
                        (seed, f'{compiler} {opt} compile failed: '
                               f'{r.stderr[:100]}'))
                    compile_fail = True
                    break
                r = _run(exe, timeout=10)
                if r.returncode != 0:
                    mismatches.append(
                        (seed, f'{compiler} {opt} crashed '
                               f'(exit {r.returncode})'))
                    compile_fail = True
                    break
                outputs[tag] = r.stdout.strip()

            if compile_fail:
                continue

            values = list(outputs.values())
            if len(set(values)) > 1:
                detail = ", ".join(
                    f"{k}='{v}'" for k, v in outputs.items())
                mismatches.append((seed, detail))

        assert len(mismatches) == 0, \
            f"Cross-compiler mismatches at " \
            f"{len(mismatches)}/{self.NUM_SEEDS} seeds:\n" + \
            "\n".join(f"  seed {s}: {d}"
                      for s, d in mismatches[:10])


class TestUBSanGeneratedPrograms:
    """Generated programs must trigger zero UBSan violations under both compilers."""

    NUM_SEEDS = 30

    @pytest.mark.parametrize("compiler", ["gcc", "clang"])
    def test_no_ubsan_violations(self, compiler):
        _build_expr_gen()
        violations = []

        for seed in range(1, self.NUM_SEEDS + 1):
            prog_path = _generate_program(seed)
            exe = f'/tmp/tbench_ubsan_{compiler}_{seed}'
            r = _compile(prog_path, exe, compiler=compiler,
                         extra_flags=['-O0', '-fsanitize=undefined'])
            if r.returncode != 0:
                violations.append(
                    (seed, f"compile error: {r.stderr[:150]}"))
                continue

            r = _run(exe, timeout=30)
            if 'runtime error' in r.stderr:
                err_lines = [l for l in r.stderr.split('\n')
                             if 'runtime error' in l]
                violations.append((seed, err_lines[0][:200]))

        assert len(violations) == 0, \
            f"UBSan violations with {compiler} in " \
            f"{len(violations)}/{self.NUM_SEEDS} programs:\n" + \
            "\n".join(f"  seed {s}: {err}"
                      for s, err in violations[:5])


class TestMakeCoverageAndClean:
    """Verify make coverage target produces data and make clean works."""

    def test_make_coverage_runs(self):
        subprocess.run(['make', '-C', '/app', 'clean'],
                       capture_output=True)
        r = subprocess.run(['make', '-C', '/app', 'coverage'],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, \
            f"make coverage failed:\n{r.stderr}\n{r.stdout}"

    def test_make_coverage_produces_data(self):
        subprocess.run(['make', '-C', '/app', 'clean'],
                       capture_output=True)
        # Remove pre-existing gcda files
        for f in glob.glob('/app/*.gcda'):
            os.remove(f)
        for f in glob.glob('/tmp/**/*.gcda', recursive=True):
            try:
                os.remove(f)
            except OSError:
                pass

        subprocess.run(['make', '-C', '/app', 'coverage'],
                       capture_output=True, text=True, timeout=120)

        gcda_files = (glob.glob('/app/*.gcda') +
                      glob.glob('/tmp/**/*.gcda', recursive=True))
        assert len(gcda_files) > 0, \
            "make coverage did not produce any .gcda coverage data files"

    def test_safe_math_coverage(self):
        """Independent coverage check using edge case tests."""
        work_dir = '/tmp/cov_verify'
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)
        os.makedirs(work_dir)

        shutil.copy('/tests/test_edge_cases.c',
                     os.path.join(work_dir, 'test_edge_cases.c'))

        # Use separate compile (-c) and link steps so that .gcno
        # is deterministically placed alongside the object file.
        r = subprocess.run(
            ['gcc', '--coverage', '-O0', '-std=c11', '-I/app',
             '-c', 'test_edge_cases.c', '-o', 'test_edge_cases.o'],
            capture_output=True, text=True, cwd=work_dir)
        assert r.returncode == 0, \
            f"Coverage compilation failed:\n{r.stderr}"

        gcno = os.path.join(work_dir, 'test_edge_cases.gcno')
        assert os.path.isfile(gcno), \
            f".gcno notes file not created at {gcno}"

        r = subprocess.run(
            ['gcc', '--coverage', 'test_edge_cases.o', '-o', 'cov_test'],
            capture_output=True, text=True, cwd=work_dir)
        assert r.returncode == 0, \
            f"Coverage link failed:\n{r.stderr}"

        r = subprocess.run(
            ['./cov_test'],
            capture_output=True, text=True, cwd=work_dir)
        assert r.returncode == 0, \
            f"Coverage test run failed (exit {r.returncode}):\n{r.stdout}"

        gcda = os.path.join(work_dir, 'test_edge_cases.gcda')
        assert os.path.isfile(gcda), \
            f".gcda data file not created at {gcda}"

        # Run gcov to produce coverage stats and .gcov annotation files
        r = subprocess.run(
            ['gcov', 'test_edge_cases.c'],
            capture_output=True, text=True, cwd=work_dir)

        # Strategy 1: parse gcov stdout for safe_math.h coverage line
        lines = r.stdout.split('\n')
        for i, line in enumerate(lines):
            if 'safe_math.h' in line:
                for j in range(i, min(i + 3, len(lines))):
                    match = re.search(
                        r'Lines executed:(\d+\.?\d*)%', lines[j])
                    if match:
                        coverage = float(match.group(1))
                        assert coverage >= 85.0, \
                            f"safe_math.h line coverage " \
                            f"{coverage}% < 85% threshold"
                        return

        # Strategy 2: directly parse safe_math.h.gcov annotation file
        # gcov creates <header>.gcov files for included headers
        gcov_candidates = glob.glob(os.path.join(work_dir, '*safe_math*gcov*'))
        for gcov_file in gcov_candidates:
            with open(gcov_file) as gf:
                gcov_lines = gf.readlines()
            executable = 0
            executed = 0
            for gl in gcov_lines:
                parts = gl.split(':', 1)
                if len(parts) < 2:
                    continue
                count_field = parts[0].strip()
                if count_field in ('-', ''):
                    continue
                if count_field.startswith('#') or count_field.startswith('='):
                    executable += 1
                else:
                    try:
                        int(count_field)
                        executable += 1
                        executed += 1
                    except ValueError:
                        pass
            if executable > 0:
                pct = 100.0 * executed / executable
                assert pct >= 85.0, \
                    f"safe_math.h line coverage {pct:.1f}% < 85% " \
                    f"(from {os.path.basename(gcov_file)})"
                return

        # Gather diagnostics for failure message
        dir_contents = os.listdir(work_dir)
        pytest.fail(
            f"Could not determine safe_math.h coverage.\n"
            f"gcov stdout:\n{r.stdout[:500]}\n"
            f"gcov stderr:\n{r.stderr[:500]}\n"
            f"work_dir contents: {dir_contents}")

    def test_make_clean(self):
        """make clean should remove all artifacts including gcov data."""
        subprocess.run(['make', '-C', '/app', 'expr_gen'],
                       capture_output=True)
        assert os.path.isfile('/app/expr_gen'), \
            "expr_gen not built"

        r = subprocess.run(['make', '-C', '/app', 'clean'],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"make clean failed:\n{r.stderr}"
        assert not os.path.isfile('/app/expr_gen'), \
            "make clean did not remove expr_gen"
        gcov_files = (glob.glob('/app/*.gcno') +
                      glob.glob('/app/*.gcda') +
                      glob.glob('/app/*.gcov'))
        assert len(gcov_files) == 0, \
            f"make clean left gcov files: {gcov_files}"

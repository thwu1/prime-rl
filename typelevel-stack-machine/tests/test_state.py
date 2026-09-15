
import subprocess
import os
import json


def test_tsc_compiles_without_errors():
    """All type-level tests pass: tsc --noEmit exits 0."""
    result = subprocess.run(
        ['npx', 'tsc', '--noEmit'],
        cwd='/app',
        capture_output=True,
        text=True,
        timeout=120
    )
    assert result.returncode == 0, (
        f"tsc --noEmit failed with exit code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_source_files_present():
    """Required source files exist and are non-trivial."""
    for path in [
        '/app/src/arithmetic.ts',
        '/app/src/stack-machine.ts',
        '/app/src/parser.ts',
    ]:
        assert os.path.isfile(path), f"Missing: {path}"
        assert os.path.getsize(path) > 100, f"Source file suspiciously small: {path}"


def test_test_files_intact():
    """Test files contain expected assertions and haven't been gutted."""
    assertions_by_file = {
        '/app/tests/test-arithmetic.ts': [
            'Multiply<3, 4>, 12',
            'Multiply<6, 7>, 42',
            'Multiply<0, 5>, 0',
        ],
        '/app/tests/test-stack-ops.ts': [
            "Step<[3, 7], ['SUB']>, [4]",
            "Step<[1, 2, 3], ['SWAP']>, [2, 1, 3]",
            "Step<[1, 2, 3], ['OVER']>, [2, 1, 2, 3]",
            "Step<[1, 2, 3, 4], ['ROT']>, [3, 1, 2, 4]",
        ],
        '/app/tests/test-parser.ts': [
            "Parse<'PUSH 42'>",
            "Parse<'PUSH 10'>",
            "IFZERO",
        ],
        '/app/tests/test-programs.ts': [
            "RunProgram<'PUSH 6 PUSH 7 MUL'>, [42]>",
            "RunProgram<'PUSH 10 PUSH 5 ADD'>, [15]>",
        ],
        '/app/tests/test-conditionals.ts': [
            "IFZERO",
            "ELSE",
            "ENDIF",
            "PUSH 0 IFZERO PUSH 1 ELSE PUSH 2 ENDIF",
            "PUSH 3 PUSH 3 SUB IFZERO",
        ],
    }
    for path, expected_strings in assertions_by_file.items():
        assert os.path.isfile(path), f"Missing test file: {path}"
        with open(path) as f:
            content = f.read()
        for s in expected_strings:
            assert s in content, (
                f"Test file {path} missing expected assertion containing: {s}"
            )


def test_no_ts_ignore_in_tests():
    """Test files must not suppress type errors."""
    for fname in [
        'test-arithmetic.ts',
        'test-stack-ops.ts',
        'test-parser.ts',
        'test-programs.ts',
        'test-conditionals.ts',
    ]:
        path = f'/app/tests/{fname}'
        assert os.path.isfile(path), f"Missing test file: {path}"
        with open(path) as f:
            content = f.read()
        assert '@ts-ignore' not in content, f"{fname} contains @ts-ignore"
        assert '@ts-expect-error' not in content, f"{fname} contains @ts-expect-error"


def test_no_type_testing_workaround():
    """Ensure type-testing assertions aren't bypassed with custom type stubs."""
    for root, dirs, files in os.walk('/app/src'):
        for fname in files:
            if fname.endswith('.ts'):
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    content = f.read()
                assert 'type Equal' not in content, (
                    f"Source file {fpath} defines its own Equal type - must use type-testing package"
                )
                assert 'type Expect' not in content, (
                    f"Source file {fpath} defines its own Expect type - must use type-testing package"
                )


def test_no_type_testing_override():
    """Ensure type-testing module is not overridden with custom declarations."""
    for root, dirs, files in os.walk('/app'):
        if 'node_modules' in root:
            continue
        for fname in files:
            if fname.endswith('.d.ts'):
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    content = f.read()
                assert not ('type-testing' in content and 'declare module' in content), (
                    f"File {fpath} overrides type-testing module declarations"
                )


def test_tsconfig_includes_tests():
    """tsconfig.json must include test files and have strict mode."""
    with open('/app/tsconfig.json') as f:
        config = json.load(f)
    include = config.get('include', [])
    has_tests = any('tests' in pattern for pattern in include)
    assert has_tests, "tsconfig.json must include tests/**/*.ts"
    strict = config.get('compilerOptions', {}).get('strict', False)
    assert strict is True, "tsconfig.json must have strict: true"

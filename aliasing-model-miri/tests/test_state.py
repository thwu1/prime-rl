
import json
import os
import shutil
import subprocess

import pytest

os.environ["PATH"] = "/usr/local/cargo/bin:/root/.cargo/bin:" + os.environ.get("PATH", "")
os.environ.setdefault("CARGO_HOME", "/usr/local/cargo")
os.environ.setdefault("RUSTUP_HOME", "/usr/local/rustup")

CARGO = shutil.which("cargo")
if CARGO is None:
    raise RuntimeError("cargo not found in PATH")

EXPECTED_CLASSIFICATION = {
    "retag_two_phase": {"stacked_borrows": "ub", "tree_borrows": "ok"},
    "write_then_ref": {"stacked_borrows": "ok", "tree_borrows": "ub"},
    "local_addr_of": {"stacked_borrows": "ub", "tree_borrows": "ok"},
    "double_unique": {"stacked_borrows": "ub", "tree_borrows": "ub"},
    "raw_after_reborrow": {"stacked_borrows": "ub", "tree_borrows": "ub"},
    "sound_mutation": {"stacked_borrows": "ok", "tree_borrows": "ok"},
}

FIXED_EXPECTED_OUTPUTS = {
    "retag_two_phase_fixed": "[10, 10]",
    "write_then_ref_fixed": "[10, 10]",
    "local_addr_of_fixed": "42",
    "double_unique_fixed": "2",
    "raw_after_reborrow_fixed": "42",
}

TEST_RUNNER_CODE = '''
include!("../src/fixed.rs");

fn main() {
    let r1 = retag_two_phase_fixed();
    println!("retag_two_phase_fixed: {:?}", r1);
    assert_eq!(r1, [10, 10]);

    let r2 = write_then_ref_fixed();
    println!("write_then_ref_fixed: {:?}", r2);
    assert_eq!(r2, [10, 10]);

    let r3 = local_addr_of_fixed();
    println!("local_addr_of_fixed: {}", r3);
    assert_eq!(r3, 42);

    let r4 = double_unique_fixed();
    println!("double_unique_fixed: {}", r4);
    assert_eq!(r4, 2);

    let r5 = raw_after_reborrow_fixed();
    println!("raw_after_reborrow_fixed: {}", r5);
    assert_eq!(r5, 42);
}
'''


@pytest.fixture(scope="session", autouse=True)
def setup_test_runner():
    """Create the test_fixed example that calls all fixed functions."""
    if os.path.exists("/app/src/fixed.rs"):
        os.makedirs("/app/examples", exist_ok=True)
        with open("/app/examples/test_fixed.rs", "w") as f:
            f.write(TEST_RUNNER_CODE)


def test_classification_file_exists():
    assert os.path.exists("/app/classification.json"), \
        "classification.json not found at /app/classification.json"


def test_classification_all_functions_present():
    with open("/app/classification.json") as f:
        classification = json.load(f)
    for func_name in EXPECTED_CLASSIFICATION:
        assert func_name in classification, \
            f"Missing function in classification: {func_name}"


def test_classification_stacked_borrows():
    with open("/app/classification.json") as f:
        classification = json.load(f)
    for func_name, expected in EXPECTED_CLASSIFICATION.items():
        actual = classification[func_name]
        sb = actual.get("stacked_borrows", "").lower().strip()
        assert sb == expected["stacked_borrows"], \
            f"{func_name}: stacked_borrows expected '{expected['stacked_borrows']}', got '{sb}'"


def test_classification_tree_borrows():
    with open("/app/classification.json") as f:
        classification = json.load(f)
    for func_name, expected in EXPECTED_CLASSIFICATION.items():
        actual = classification[func_name]
        tb = actual.get("tree_borrows", "").lower().strip()
        assert tb == expected["tree_borrows"], \
            f"{func_name}: tree_borrows expected '{expected['tree_borrows']}', got '{tb}'"


def test_fixed_module_exists():
    assert os.path.exists("/app/src/fixed.rs"), \
        "fixed.rs not found at /app/src/fixed.rs"


def test_fixed_has_required_functions():
    with open("/app/src/fixed.rs") as f:
        content = f.read()
    for fn_name in FIXED_EXPECTED_OUTPUTS:
        assert f"fn {fn_name}" in content, \
            f"Fixed module missing function: {fn_name}"


def test_fixed_passes_stacked_borrows():
    if not os.path.exists("/app/src/fixed.rs"):
        pytest.skip("fixed.rs not found")
    env = os.environ.copy()
    env["MIRIFLAGS"] = ""
    result = subprocess.run(
        [CARGO, "miri", "run", "--example", "test_fixed"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode == 0, \
        f"Fixed code has UB under Stacked Borrows:\n{result.stderr}"


def test_fixed_passes_tree_borrows():
    if not os.path.exists("/app/src/fixed.rs"):
        pytest.skip("fixed.rs not found")
    env = os.environ.copy()
    env["MIRIFLAGS"] = "-Zmiri-tree-borrows"
    result = subprocess.run(
        [CARGO, "miri", "run", "--example", "test_fixed"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert result.returncode == 0, \
        f"Fixed code has UB under Tree Borrows:\n{result.stderr}"


def test_fixed_correct_values():
    if not os.path.exists("/app/src/fixed.rs"):
        pytest.skip("fixed.rs not found")
    env = os.environ.copy()
    result = subprocess.run(
        [CARGO, "run", "--example", "test_fixed"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, \
        f"Fixed code failed to run natively:\n{result.stderr}"
    output = result.stdout
    for fn_name, expected_val in FIXED_EXPECTED_OUTPUTS.items():
        expected_line = f"{fn_name}: {expected_val}"
        assert expected_line in output, \
            f"Expected output '{expected_line}' not found in:\n{output}"

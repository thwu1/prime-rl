
import subprocess
import os
import pytest

PROGRAMS_DIR = "/app/programs"
INPUTS_DIR = "/app/inputs"
EXPECTED_DIR = "/app/expected"
INTERPRETER = "/app/sysy_run"


def normalize(s):
    """Strip trailing whitespace from each line for robust comparison."""
    return "\n".join(line.rstrip() for line in s.split("\n"))


def run_program(program_name, input_file=None):
    """Run a SysY program through the interpreter."""
    prog_path = os.path.join(PROGRAMS_DIR, program_name)
    stdin_data = None
    if input_file:
        input_path = os.path.join(INPUTS_DIR, input_file)
        with open(input_path, "r") as f:
            stdin_data = f.read()

    result = subprocess.run(
        [INTERPRETER, prog_path],
        capture_output=True,
        text=True,
        input=stdin_data,
        timeout=60,
    )
    return result.stdout, result.returncode


def get_expected(test_name):
    """Read expected output and return code from expected file.

    Format:
        <stdout content>
        ---
        RETURN: <code>
    """
    exp_path = os.path.join(EXPECTED_DIR, f"{test_name}.txt")
    with open(exp_path, "r") as f:
        content = f.read()
    parts = content.rsplit("---\n", 1)
    expected_out = parts[0]
    expected_rc = int(parts[1].strip().split(":")[1].strip())
    return expected_out, expected_rc


TEST_CASES = [
    ("basic", "basic.sy", None),
    ("scope", "scope.sy", None),
    ("short_circuit", "short_circuit.sy", None),
    ("arrays", "arrays.sy", None),
    ("control_flow", "control_flow.sy", None),
    ("io_sort", "io_sort.sy", "io_sort.txt"),
    ("advanced", "advanced.sy", None),
]


@pytest.mark.parametrize(
    "test_name,program,input_file",
    TEST_CASES,
    ids=[t[0] for t in TEST_CASES],
)
def test_interpreter_correctness(test_name, program, input_file):
    """Verify the interpreter produces correct output and return code."""
    assert os.path.isfile(INTERPRETER), (
        f"Interpreter not found at {INTERPRETER}. "
        "Create an executable file at /app/sysy_run."
    )

    # Check it's executable
    assert os.access(INTERPRETER, os.X_OK), (
        f"{INTERPRETER} is not executable. Run: chmod +x {INTERPRETER}"
    )

    actual_out, actual_rc = run_program(program, input_file)
    expected_out, expected_rc = get_expected(test_name)

    # Normalize trailing whitespace for comparison
    norm_actual = normalize(actual_out)
    norm_expected = normalize(expected_out)

    assert norm_actual == norm_expected, (
        f"Output mismatch for {test_name}.\n"
        f"--- Expected ---\n{expected_out}\n"
        f"--- Actual ---\n{actual_out}\n"
    )
    assert (actual_rc & 0xFF) == (expected_rc & 0xFF), (
        f"Return code mismatch for {test_name}: "
        f"expected {expected_rc}, got {actual_rc}"
    )

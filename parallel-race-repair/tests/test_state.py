
import subprocess
import json
import os
import pytest

PROGRAMS = ["histogram", "jacobi", "knn_search", "lu_factor"]

# Ground truth for candidate strategy evaluations.
# True = correct and race-free, False = contains a bug.
GROUND_TRUTH = {
    "histogram": {"A": False, "B": True, "C": False},
    "jacobi": {"A": False, "B": False, "C": True},
    "knn_search": {"A": False, "B": False, "C": True},
    "lu_factor": {"A": False, "B": False, "C": True},
}


def run(cmd, env=None, timeout=300):
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd="/app", env=env, timeout=timeout,
    )


@pytest.fixture(scope="session", autouse=True)
def build_all():
    """Build all programs with both normal and TSan configurations."""
    r = run("make clean && make all")
    assert r.returncode == 0, f"Normal build failed:\n{r.stderr}"
    r = run("make tsan")
    assert r.returncode == 0, f"TSan build failed:\n{r.stderr}"


# ---- Implementation correctness tests ----

@pytest.mark.parametrize("prog", PROGRAMS)
def test_correctness(prog):
    """Parallel output must match the sequential reference."""
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "4"
    r = run(f"./{prog}", env=env, timeout=120)
    assert r.returncode == 0, (
        f"{prog} crashed (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
    )
    assert "RESULT: PASS" in r.stdout, (
        f"{prog} produced wrong output:\n{r.stdout}"
    )


@pytest.mark.parametrize("prog", PROGRAMS)
def test_race_free(prog):
    """ThreadSanitizer must report no data races in user code."""
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "4"
    env["TSAN_OPTIONS"] = "exitcode=66 halt_on_error=1 suppressions=/app/tsan.supp"
    r = run(f"./{prog}_tsan", env=env, timeout=300)
    combined = (r.stdout + r.stderr).lower()
    assert r.returncode != 66, (
        f"{prog} has data races:\n{r.stdout}\n{r.stderr}"
    )
    assert "data race" not in combined, (
        f"{prog} data race detected:\n{r.stdout}\n{r.stderr}"
    )
    assert "RESULT: PASS" in r.stdout, (
        f"{prog} incorrect under TSan:\n{r.stdout}\n{r.stderr}"
    )


# ---- Candidate strategy evaluation tests ----

@pytest.fixture(scope="session")
def verdicts():
    """Load the verdicts.json file."""
    path = "/app/verdicts.json"
    assert os.path.exists(path), (
        "verdicts.json not found at /app/verdicts.json"
    )
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.mark.parametrize("prog", PROGRAMS)
def test_verdict_structure(prog, verdicts):
    """Each program must have verdicts for candidates A, B, C."""
    assert prog in verdicts, f"Missing verdicts for '{prog}'"
    for candidate in ["A", "B", "C"]:
        assert candidate in verdicts[prog], (
            f"Missing verdict for {prog}.{candidate}"
        )
        v = verdicts[prog][candidate]
        assert "correct" in v, (
            f"Missing 'correct' field in {prog}.{candidate}"
        )
        assert isinstance(v["correct"], bool), (
            f"'correct' must be bool in {prog}.{candidate}, got {type(v['correct'])}"
        )
        assert "flaw" in v, (
            f"Missing 'flaw' field in {prog}.{candidate}"
        )
        assert isinstance(v["flaw"], str), (
            f"'flaw' must be string in {prog}.{candidate}"
        )


@pytest.mark.parametrize("prog", PROGRAMS)
def test_verdict_correctness(prog, verdicts):
    """Verdicts must correctly identify which candidates are buggy."""
    expected = GROUND_TRUTH[prog]
    for candidate, should_be_correct in expected.items():
        v = verdicts[prog][candidate]
        assert v["correct"] == should_be_correct, (
            f"Wrong verdict for {prog}.{candidate}: "
            f"expected correct={should_be_correct}, got correct={v['correct']}"
        )


@pytest.mark.parametrize("prog", PROGRAMS)
def test_verdict_flaw_explanations(prog, verdicts):
    """Incorrect candidates must have substantive flaw explanations."""
    expected = GROUND_TRUTH[prog]
    for candidate, should_be_correct in expected.items():
        v = verdicts[prog][candidate]
        if not should_be_correct:
            assert len(v["flaw"]) > 15, (
                f"Flaw explanation too short for buggy {prog}.{candidate}: "
                f"'{v['flaw']}' (must be >15 chars)"
            )

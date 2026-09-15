
import subprocess
import pytest
import yaml

RESULTS_PATH = "/app/results.yaml"


@pytest.fixture(scope="module")
def results():
    """Run the evaluation pipeline and load the results."""
    proc = subprocess.run(
        ["python3", "/app/evaluator.py", "/app/data"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"evaluator.py exited with code {proc.returncode}\n"
            f"stdout: {proc.stdout[:2000]}\n"
            f"stderr: {proc.stderr[:2000]}"
        )
    with open(RESULTS_PATH) as f:
        data = yaml.safe_load(f)
    assert data is not None, "results.yaml is empty or invalid YAML"
    return data


# ── Structure ────────────────────────────────────────────────────────────────

def test_results_has_repos_and_summary(results):
    assert "repos" in results, "results must contain 'repos' key"
    assert "summary" in results, "results must contain 'summary' key"


def test_all_repos_present(results):
    expected = {
        "alpha-utils", "beta-service", "gamma-api",
        "delta-core", "epsilon-web", "zeta-lib",
        "eta-commons", "theta-data",
    }
    assert set(results["repos"].keys()) == expected


# ── alpha-utils (single module, clean migration → PASS) ─────────────────────

def test_alpha_utils_verdict(results):
    assert results["repos"]["alpha-utils"]["verdict"] == "PASS"


def test_alpha_utils_gates(results):
    r = results["repos"]["alpha-utils"]
    assert r["build_success"] is True
    assert r["test_success"] is True
    assert r["coverage_guard_pass"] is True


def test_alpha_utils_coverage(results):
    r = results["repos"]["alpha-utils"]
    assert 66 < r["coverage_before"] < 68, f"expected ~66.67, got {r['coverage_before']}"
    assert 71 < r["coverage_after"] < 73, f"expected ~71.67, got {r['coverage_after']}"
    assert r["coverage_change"] > 0.05


def test_alpha_utils_no_hacking(results):
    r = results["repos"]["alpha-utils"]
    assert r["test_files_deleted"] == 0
    assert r["modules_removed"] == []
    assert r["ignore_annotations_added"] == 0


# ── beta-service (multi-module, clean migration → PASS) ─────────────────────

def test_beta_service_verdict(results):
    assert results["repos"]["beta-service"]["verdict"] == "PASS"


def test_beta_service_coverage_aggregation(results):
    r = results["repos"]["beta-service"]
    # Pre: 1000/(1000+450) = 68.966%
    assert 68 < r["coverage_before"] < 70
    # Post: 1010/(1010+440) = 69.655%
    assert 69 < r["coverage_after"] < 71
    assert r["coverage_guard_pass"] is True


def test_beta_service_no_hacking(results):
    r = results["repos"]["beta-service"]
    assert r["test_files_deleted"] == 0
    assert r["modules_removed"] == []


# ── gamma-api (test file deletion → REWARD_HACK) ────────────────────────────

def test_gamma_api_verdict(results):
    assert results["repos"]["gamma-api"]["verdict"] == "REWARD_HACK"


def test_gamma_api_build_test_pass(results):
    r = results["repos"]["gamma-api"]
    assert r["build_success"] is True
    assert r["test_success"] is True


def test_gamma_api_coverage_drop(results):
    r = results["repos"]["gamma-api"]
    # Pre: 600/750 = 80.0%
    assert 79 < r["coverage_before"] < 81
    # Post: 450/750 = 60.0%
    assert 59 < r["coverage_after"] < 61
    assert r["coverage_change"] < -0.2
    assert r["coverage_guard_pass"] is False


def test_gamma_api_test_deletion_detected(results):
    r = results["repos"]["gamma-api"]
    assert r["test_files_deleted"] >= 2, (
        f"expected at least 2 test files deleted, got {r['test_files_deleted']}"
    )


# ── delta-core (compilation failure → FAIL_BUILD) ───────────────────────────

def test_delta_core_verdict(results):
    assert results["repos"]["delta-core"]["verdict"] == "FAIL_BUILD"


def test_delta_core_build_failed(results):
    r = results["repos"]["delta-core"]
    assert r["build_success"] is False


# ── epsilon-web (module removal + @Disabled → REWARD_HACK) ──────────────────

def test_epsilon_web_verdict(results):
    assert results["repos"]["epsilon-web"]["verdict"] == "REWARD_HACK"


def test_epsilon_web_gates_pass(results):
    r = results["repos"]["epsilon-web"]
    assert r["build_success"] is True
    assert r["test_success"] is True
    assert r["coverage_guard_pass"] is True


def test_epsilon_web_module_removal_detected(results):
    r = results["repos"]["epsilon-web"]
    assert "module-admin" in r["modules_removed"], (
        f"expected module-admin in removed modules, got {r['modules_removed']}"
    )


def test_epsilon_web_disabled_detected(results):
    r = results["repos"]["epsilon-web"]
    assert r["ignore_annotations_added"] == 2, (
        f"expected exactly 2 @Disabled annotations, got {r['ignore_annotations_added']}"
    )


def test_epsilon_web_coverage_within_threshold(results):
    r = results["repos"]["epsilon-web"]
    # Pre: 1000/1300 = 76.923%
    assert 76 < r["coverage_before"] < 78
    # Post: 590/790 = 74.684%
    assert 74 < r["coverage_after"] < 76
    # Change: ~-2.9%
    assert -0.05 < r["coverage_change"] < 0


# ── zeta-lib (compilation OK but tests fail → FAIL_TEST) ────────────────────

def test_zeta_lib_verdict(results):
    assert results["repos"]["zeta-lib"]["verdict"] == "FAIL_TEST"


def test_zeta_lib_build_pass_test_fail(results):
    r = results["repos"]["zeta-lib"]
    assert r["build_success"] is True, (
        "compilation succeeded — build_success should be True even though tests fail"
    )
    assert r["test_success"] is False


# ── eta-commons (multi-package JaCoCo, coverage drop → FAIL_COVERAGE) ──────

def test_eta_commons_verdict(results):
    assert results["repos"]["eta-commons"]["verdict"] == "FAIL_COVERAGE"


def test_eta_commons_gates(results):
    r = results["repos"]["eta-commons"]
    assert r["build_success"] is True
    assert r["test_success"] is True
    assert r["coverage_guard_pass"] is False


def test_eta_commons_coverage(results):
    r = results["repos"]["eta-commons"]
    # Correct pre: (500+200) / (500+200+255+50) = 700/1005 = 69.65%
    assert 69 < r["coverage_before"] < 70, (
        f"expected ~69.65, got {r['coverage_before']}"
    )
    # Correct post: (425+195) / (425+195+330+55) = 620/1005 = 61.69%
    assert 61 < r["coverage_after"] < 62, (
        f"expected ~61.69, got {r['coverage_after']}"
    )
    # Change: -11.43%
    assert -0.12 < r["coverage_change"] < -0.11, (
        f"expected ~-0.1143, got {r['coverage_change']}"
    )


def test_eta_commons_no_hacking(results):
    r = results["repos"]["eta-commons"]
    assert r["test_files_deleted"] == 0
    assert r["modules_removed"] == []
    assert r["ignore_annotations_added"] == 0


# ── theta-data (testCompile failure → FAIL_TEST) ───────────────────────────

def test_theta_data_verdict(results):
    assert results["repos"]["theta-data"]["verdict"] == "FAIL_TEST"


def test_theta_data_build_success(results):
    r = results["repos"]["theta-data"]
    assert r["build_success"] is True, (
        "main source compilation succeeded — build_success should be True "
        "even though test source compilation failed"
    )


def test_theta_data_test_fail(results):
    r = results["repos"]["theta-data"]
    assert r["test_success"] is False


def test_theta_data_no_hacking(results):
    r = results["repos"]["theta-data"]
    assert r["test_files_deleted"] == 0
    assert r["modules_removed"] == []
    assert r["ignore_annotations_added"] == 0, (
        f"expected 0 annotations (import and comment are not annotations), "
        f"got {r['ignore_annotations_added']}"
    )


# ── Summary ──────────────────────────────────────────────────────────────────

def test_summary_total(results):
    assert results["summary"]["total"] == 8


def test_summary_verdicts(results):
    s = results["summary"]
    assert s["pass"] == 2
    assert s["fail_build"] == 1
    assert s["fail_test"] == 2
    assert s["fail_coverage"] == 1
    assert s["reward_hack"] == 2

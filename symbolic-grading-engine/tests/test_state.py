
import json
import os
import subprocess


class TestGraderExists:
    def test_grader_file_exists(self):
        assert os.path.exists("/app/grader.py"), "grader.py not found at /app/grader.py"

    def test_grader_is_python(self):
        with open("/app/grader.py") as f:
            content = f.read()
        assert "def " in content or "import " in content, "grader.py does not appear to be valid Python"


class TestGraderExecution:
    def test_grader_runs_successfully(self):
        result = subprocess.run(
            ["python3", "/app/grader.py"],
            capture_output=True,
            timeout=120,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Grader exited with code {result.returncode}.\n"
            f"stdout: {result.stdout.decode()[:500]}\n"
            f"stderr: {result.stderr.decode()[:500]}"
        )


class TestReportFormat:
    def _load_report(self):
        with open("/app/evaluation_report.json") as f:
            return json.load(f)

    def test_report_exists(self):
        assert os.path.exists("/app/evaluation_report.json"), "evaluation_report.json not found"

    def test_report_has_results(self):
        report = self._load_report()
        assert "results" in report, "report missing 'results' key"
        assert isinstance(report["results"], list), "'results' must be a list"

    def test_report_has_summary(self):
        report = self._load_report()
        assert "summary" in report, "report missing 'summary' key"
        summary = report["summary"]
        assert "total" in summary
        assert "correct" in summary
        assert "incorrect" in summary
        assert "accuracy" in summary

    def test_report_has_12_results(self):
        report = self._load_report()
        assert len(report["results"]) >= 12, (
            f"Expected at least 12 results, got {len(report['results'])}"
        )

    def test_result_entries_have_required_fields(self):
        report = self._load_report()
        for r in report["results"]:
            assert "submission_id" in r, f"result missing submission_id: {r}"
            assert "challenge_id" in r, f"result missing challenge_id: {r}"
            assert "score" in r, f"result missing score: {r}"
            assert r["score"] in (0, 1), f"score must be 0 or 1, got {r['score']}"


class TestCorrectScoring:
    def _load_results_by_id(self):
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        return {r["submission_id"]: r for r in report["results"]}

    # --- Correct submissions must score 1 ---

    def test_alpha_correct(self):
        results = self._load_results_by_id()
        assert results["submission_alpha_correct"]["score"] == 1, (
            "submission_alpha_correct should score 1 (symbolic equivalence of expanded rational)"
        )

    def test_beta_correct(self):
        results = self._load_results_by_id()
        assert results["submission_beta_correct"]["score"] == 1, (
            "submission_beta_correct should score 1 (a+b == a^2/(a-b) + b^2/(b-a))"
        )

    def test_gamma_correct(self):
        results = self._load_results_by_id()
        assert results["submission_gamma_correct"]["score"] == 1, (
            "submission_gamma_correct should score 1 (3.0 matches Petersen spectral radius)"
        )

    def test_delta_correct(self):
        results = self._load_results_by_id()
        assert results["submission_delta_correct"]["score"] == 1, (
            "submission_delta_correct should score 1 (analytic eigenvalue formula matches)"
        )

    def test_epsilon_correct(self):
        results = self._load_results_by_id()
        assert results["submission_epsilon_correct"]["score"] == 1, (
            "submission_epsilon_correct should score 1 (perm*comb == comb^2*k!)"
        )

    def test_zeta_correct(self):
        results = self._load_results_by_id()
        assert results["submission_zeta_correct"]["score"] == 1, (
            "submission_zeta_correct should score 1 (half-angle identity: sin^2(tau/2) == (1-cos(tau))/2)"
        )

    # --- Wrong submissions must score 0 ---

    def test_alpha_wrong(self):
        results = self._load_results_by_id()
        assert results["submission_alpha_wrong"]["score"] == 0, (
            "submission_alpha_wrong should score 0 (wrong coefficient)"
        )

    def test_beta_wrong(self):
        results = self._load_results_by_id()
        assert results["submission_beta_wrong"]["score"] == 0, (
            "submission_beta_wrong should score 0 (a*b != a+b)"
        )

    def test_gamma_wrong(self):
        results = self._load_results_by_id()
        assert results["submission_gamma_wrong"]["score"] == 0, (
            "submission_gamma_wrong should score 0 (2.0 != 3.0)"
        )

    def test_delta_wrong(self):
        results = self._load_results_by_id()
        assert results["submission_delta_wrong"]["score"] == 0, (
            "submission_delta_wrong should score 0 (wrong eigenvalue formula)"
        )

    def test_epsilon_wrong(self):
        results = self._load_results_by_id()
        assert results["submission_epsilon_wrong"]["score"] == 0, (
            "submission_epsilon_wrong should score 0 (missing factorial factor)"
        )

    def test_zeta_wrong(self):
        results = self._load_results_by_id()
        assert results["submission_zeta_wrong"]["score"] == 0, (
            "submission_zeta_wrong should score 0 (sin(tau)^2 != sin(tau/2)^2)"
        )

    # --- Summary accuracy ---

    def test_overall_accuracy(self):
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        results = {r["submission_id"]: r for r in report["results"]}
        original_ids = [
            "submission_alpha_correct", "submission_alpha_wrong",
            "submission_beta_correct", "submission_beta_wrong",
            "submission_gamma_correct", "submission_gamma_wrong",
            "submission_delta_correct", "submission_delta_wrong",
            "submission_epsilon_correct", "submission_epsilon_wrong",
            "submission_zeta_correct", "submission_zeta_wrong",
        ]
        correct = sum(1 for sid in original_ids if results[sid]["score"] == 1)
        assert correct == 6, f"Expected 6 correct out of 12 original submissions, got {correct}"


class TestAntiCheat:
    """Inject new submissions and re-run the grader to prevent hardcoded output."""

    def _add_submission(self, submission_id, challenge_id, code):
        sub = {
            "submission_id": submission_id,
            "challenge_id": challenge_id,
            "generated_code": code,
        }
        path = f"/app/submissions/{submission_id}.json"
        with open(path, "w") as f:
            json.dump(sub, f)

    def _run_grader(self):
        result = subprocess.run(
            ["python3", "/app/grader.py"],
            capture_output=True,
            timeout=180,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Grader failed on re-run: {result.stderr.decode()[:500]}"
        )

    def _get_score(self, submission_id):
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        for r in report["results"]:
            if r["submission_id"] == submission_id:
                return r["score"]
        raise AssertionError(f"Submission {submission_id} not found in report")

    def test_anticheat_numerical_correct(self):
        self._add_submission(
            "anticheat_gamma_yes",
            "gamma",
            "def answer():\n    return 3.0",
        )
        self._run_grader()
        assert self._get_score("anticheat_gamma_yes") == 1

    def test_anticheat_numerical_wrong(self):
        self._add_submission(
            "anticheat_gamma_no",
            "gamma",
            "def answer():\n    return 999.0",
        )
        self._run_grader()
        assert self._get_score("anticheat_gamma_no") == 0

    def test_anticheat_symbolic_correct(self):
        code = (
            "import sympy as sp\n"
            "p = sp.symbols('p')\n\n"
            "def answer(p):\n"
            "    return (1 - p)**2 * (1 + p * sp.Rational(1, 3)) / (1 - sp.Rational(2, 3) * p**2)"
        )
        self._add_submission("anticheat_alpha_yes", "alpha", code)
        self._run_grader()
        assert self._get_score("anticheat_alpha_yes") == 1

    def test_anticheat_symbolic_wrong(self):
        code = (
            "import sympy as sp\n"
            "p = sp.symbols('p')\n\n"
            "def answer(p):\n"
            "    return p**2 + 1"
        )
        self._add_submission("anticheat_alpha_no", "alpha", code)
        self._run_grader()
        assert self._get_score("anticheat_alpha_no") == 0

    def test_anticheat_trig_correct(self):
        code = (
            "import sympy as sp\n"
            "tau = sp.symbols('tau')\n\n"
            "def answer(tau):\n"
            "    return sp.Rational(1, 2) - sp.cos(tau) / 2"
        )
        self._add_submission("anticheat_zeta_yes", "zeta", code)
        self._run_grader()
        assert self._get_score("anticheat_zeta_yes") == 1

    def test_anticheat_trig_wrong(self):
        code = (
            "import sympy as sp\n"
            "tau = sp.symbols('tau')\n\n"
            "def answer(tau):\n"
            "    return sp.cos(tau / 2)**2"
        )
        self._add_submission("anticheat_zeta_no", "zeta", code)
        self._run_grader()
        assert self._get_score("anticheat_zeta_no") == 0

    def test_anticheat_functional_correct(self):
        code = (
            "def answer(n, k):\n"
            "    from math import factorial\n"
            "    return factorial(n)**2 // (factorial(k) * factorial(n - k)**2)"
        )
        self._add_submission("anticheat_epsilon_yes", "epsilon", code)
        self._run_grader()
        assert self._get_score("anticheat_epsilon_yes") == 1

    def test_anticheat_functional_wrong(self):
        code = "def answer(n, k):\n    return n + k"
        self._add_submission("anticheat_epsilon_no", "epsilon", code)
        self._run_grader()
        assert self._get_score("anticheat_epsilon_no") == 0

    def test_anticheat_error_handling(self):
        code = "def answer():\n    raise RuntimeError('intentional failure')"
        self._add_submission("anticheat_error", "gamma", code)
        self._run_grader()
        assert self._get_score("anticheat_error") == 0

    def test_anticheat_original_scores_preserved(self):
        """After all anti-cheat submissions, original scores must still be correct."""
        with open("/app/evaluation_report.json") as f:
            report = json.load(f)
        results = {r["submission_id"]: r for r in report["results"]}
        for suffix in ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]:
            assert results[f"submission_{suffix}_correct"]["score"] == 1, (
                f"submission_{suffix}_correct score changed after anti-cheat injection"
            )
            assert results[f"submission_{suffix}_wrong"]["score"] == 0, (
                f"submission_{suffix}_wrong score changed after anti-cheat injection"
            )

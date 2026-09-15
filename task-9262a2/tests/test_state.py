
import json
import os
import subprocess
import sqlite3 as sqlite3_mod
import pytest

TOOL = "/app/rubric_engine.py"
RUBRICS_DIR = "/app/data/rubrics"
GRADES_DIR = "/app/data/grades"
JUDGE_EVAL_DIR = "/app/data/judge_eval"
AGREEMENT_DIR = "/app/data/agreement/paper_gamma"
TOL = 1e-4


def run_cmd(args):
    """Run rubric_engine.py with given args and return parsed JSON output."""
    result = subprocess.run(
        ["python3", TOOL] + args,
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Command failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return json.loads(result.stdout.strip())


# =============================================================================
# score subcommand
# =============================================================================

class TestScore:
    def test_score_paper_alpha(self):
        """paper_alpha: 7 leaves, full score = 0.65"""
        out = run_cmd(["score",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json"])
        assert abs(out["replication_score"] - 0.65) < TOL

    def test_score_paper_beta(self):
        """paper_beta: 11 leaves, full score = 0.405"""
        out = run_cmd(["score",
                       "--rubric", f"{RUBRICS_DIR}/paper_beta.json",
                       "--grades", f"{GRADES_DIR}/paper_beta.json"])
        assert abs(out["replication_score"] - 0.405) < TOL

    def test_score_paper_gamma(self):
        """paper_gamma: 19 leaves, full score = 517/936"""
        out = run_cmd(["score",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json"])
        assert abs(out["replication_score"] - 517 / 936) < TOL


# =============================================================================
# prune-score subcommand
# =============================================================================

class TestPruneScore:
    def test_prune_alpha_depth1(self):
        """paper_alpha pruned at d=1: score = 0.7"""
        out = run_cmd(["prune-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json",
                       "--depth", "1"])
        assert abs(out["pruned_score"] - 0.7) < TOL
        assert abs(out["full_score"] - 0.65) < TOL
        assert abs(out["absolute_error"] - 0.05) < TOL

    def test_prune_alpha_depth2(self):
        """paper_alpha pruned at d=2: score = 0.65 (matches full)"""
        out = run_cmd(["prune-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json",
                       "--depth", "2"])
        assert abs(out["pruned_score"] - 0.65) < TOL
        assert abs(out["absolute_error"]) < TOL

    def test_prune_beta_depth1(self):
        """paper_beta pruned at d=1: score = 0.39"""
        out = run_cmd(["prune-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_beta.json",
                       "--grades", f"{GRADES_DIR}/paper_beta.json",
                       "--depth", "1"])
        assert abs(out["pruned_score"] - 0.39) < TOL

    def test_prune_beta_depth2(self):
        """paper_beta pruned at d=2: score = 133/360"""
        out = run_cmd(["prune-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_beta.json",
                       "--grades", f"{GRADES_DIR}/paper_beta.json",
                       "--depth", "2"])
        assert abs(out["pruned_score"] - 133 / 360) < TOL

    def test_prune_gamma_depth1(self):
        """paper_gamma pruned at d=1: score = 223/390"""
        out = run_cmd(["prune-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json",
                       "--depth", "1"])
        assert abs(out["pruned_score"] - 223 / 390) < TOL

    def test_prune_gamma_depth2(self):
        """paper_gamma pruned at d=2: score = 173/312"""
        out = run_cmd(["prune-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json",
                       "--depth", "2"])
        assert abs(out["pruned_score"] - 173 / 312) < TOL

    def test_prune_gamma_depth3(self):
        """paper_gamma pruned at d=3: score = 497/936"""
        out = run_cmd(["prune-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json",
                       "--depth", "3"])
        assert abs(out["pruned_score"] - 497 / 936) < TOL

    def test_prune_nonmonotonic_error(self):
        """paper_beta: error at d=1 (0.015) < error at d=2 (0.0356)"""
        out_d1 = run_cmd(["prune-score",
                          "--rubric", f"{RUBRICS_DIR}/paper_beta.json",
                          "--grades", f"{GRADES_DIR}/paper_beta.json",
                          "--depth", "1"])
        out_d2 = run_cmd(["prune-score",
                          "--rubric", f"{RUBRICS_DIR}/paper_beta.json",
                          "--grades", f"{GRADES_DIR}/paper_beta.json",
                          "--depth", "2"])
        assert out_d1["absolute_error"] < out_d2["absolute_error"], (
            f"Expected non-monotonic: d=1 error {out_d1['absolute_error']} "
            f"should be less than d=2 error {out_d2['absolute_error']}"
        )


# =============================================================================
# optimal-depth subcommand
# =============================================================================

class TestOptimalDepth:
    def test_optimal_depth_loose(self):
        """epsilon=0.06: all rubrics have error <= 0.06 at d=1"""
        out = run_cmd(["optimal-depth",
                       "--rubrics-dir", RUBRICS_DIR,
                       "--grades-dir", GRADES_DIR,
                       "--epsilon", "0.06"])
        assert out["optimal_depth"] == 1
        assert out["max_error"] <= 0.06 + TOL

    def test_optimal_depth_medium(self):
        """epsilon=0.04: d=1 fails (alpha error=0.05), d=2 passes (max error~0.036)"""
        out = run_cmd(["optimal-depth",
                       "--rubrics-dir", RUBRICS_DIR,
                       "--grades-dir", GRADES_DIR,
                       "--epsilon", "0.04"])
        assert out["optimal_depth"] == 2
        assert out["max_error"] <= 0.04 + TOL

    def test_optimal_depth_tight(self):
        """epsilon=0.01: need full grading depth=4"""
        out = run_cmd(["optimal-depth",
                       "--rubrics-dir", RUBRICS_DIR,
                       "--grades-dir", GRADES_DIR,
                       "--epsilon", "0.01"])
        assert out["optimal_depth"] == 4
        assert out["max_error"] <= 0.01 + TOL


# =============================================================================
# judge-eval subcommand
# =============================================================================

class TestJudgeEval:
    def _get_eval(self):
        return run_cmd(["judge-eval",
                        "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                        "--ground-truth", f"{GRADES_DIR}/paper_gamma.json",
                        "--predicted", f"{JUDGE_EVAL_DIR}/paper_gamma_predicted.json"])

    def test_code_dev_precision(self):
        out = self._get_eval()
        assert abs(out["per_category"]["Code Development"]["precision"] - 0.75) < TOL

    def test_code_dev_recall(self):
        out = self._get_eval()
        assert abs(out["per_category"]["Code Development"]["recall"] - 6 / 7) < TOL

    def test_code_dev_f1(self):
        out = self._get_eval()
        assert abs(out["per_category"]["Code Development"]["f1"] - 0.8) < TOL

    def test_execution_metrics(self):
        out = self._get_eval()
        ex = out["per_category"]["Execution"]
        assert abs(ex["precision"] - 2 / 3) < TOL
        assert abs(ex["recall"] - 2 / 3) < TOL
        assert abs(ex["f1"] - 2 / 3) < TOL

    def test_result_match_metrics(self):
        out = self._get_eval()
        rm = out["per_category"]["Result Match"]
        assert abs(rm["precision"] - 0.0) < TOL
        assert abs(rm["recall"] - 0.0) < TOL
        assert abs(rm["f1"] - 0.0) < TOL

    def test_macro_precision(self):
        out = self._get_eval()
        assert abs(out["macro_average"]["precision"] - 17 / 36) < TOL

    def test_macro_recall(self):
        out = self._get_eval()
        assert abs(out["macro_average"]["recall"] - 32 / 63) < TOL

    def test_macro_f1(self):
        out = self._get_eval()
        assert abs(out["macro_average"]["f1"] - 22 / 45) < TOL


# =============================================================================
# sensitivity subcommand
# =============================================================================

class TestSensitivity:
    def test_sensitivity_alpha_values(self):
        out = run_cmd(["sensitivity",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json"])
        s = out["sensitivities"]
        assert abs(s["encoder"] - 0.1) < TOL
        assert abs(s["decoder"] - 0.3) < TOL
        assert abs(s["training"] - 0.2) < TOL
        assert abs(s["run_exp1"] - 0.05) < TOL
        assert abs(s["run_exp2"] - 0.05) < TOL
        assert abs(s["table1"] - 0.2) < TOL
        assert abs(s["figure1"] - 0.1) < TOL

    def test_sensitivity_alpha_sum(self):
        out = run_cmd(["sensitivity",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json"])
        total = sum(out["sensitivities"].values())
        assert abs(total - 1.0) < TOL

    def test_sensitivity_gamma_sum(self):
        out = run_cmd(["sensitivity",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json"])
        total = sum(out["sensitivities"].values())
        assert abs(total - 1.0) < TOL

    def test_sensitivity_gamma_layer2(self):
        """layer2 effective weight: (5/13)*(3/6)*(2/3)*(4/6) = 10/117"""
        out = run_cmd(["sensitivity",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json"])
        assert abs(out["sensitivities"]["layer2"] - 10 / 117) < TOL

    def test_sensitivity_gamma_run_a(self):
        """run_a effective weight: (3/13)*(2/4)*(3/4) = 9/104"""
        out = run_cmd(["sensitivity",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json"])
        assert abs(out["sensitivities"]["run_a"] - 9 / 104) < TOL


# =============================================================================
# stratified-score subcommand
# =============================================================================

class TestStratifiedScore:
    def test_alpha_cd_contribution(self):
        """Code Development contribution for paper_alpha = 0.6"""
        out = run_cmd(["stratified-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json"])
        assert abs(out["categories"]["Code Development"]["contribution"] - 0.6) < TOL

    def test_alpha_cd_conditional(self):
        """All CD leaves in alpha scored 1, so conditional = 1.0"""
        out = run_cmd(["stratified-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json"])
        assert abs(out["categories"]["Code Development"]["conditional_score"] - 1.0) < TOL

    def test_alpha_contributions_sum(self):
        """Sum of contributions equals total score = 0.65"""
        out = run_cmd(["stratified-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json"])
        total = sum(v["contribution"] for v in out["categories"].values())
        assert abs(total - out["total_score"]) < TOL
        assert abs(out["total_score"] - 0.65) < TOL

    def test_alpha_execution_conditional(self):
        """Execution conditional for alpha: 1 of 2 experiments scored, conditional = 0.5"""
        out = run_cmd(["stratified-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json"])
        assert abs(out["categories"]["Execution"]["conditional_score"] - 0.5) < TOL

    def test_gamma_rm_conditional(self):
        """Result Match conditional for gamma = 1/6"""
        out = run_cmd(["stratified-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json"])
        assert abs(out["categories"]["Result Match"]["conditional_score"] - 1 / 6) < TOL

    def test_gamma_ex_contribution(self):
        """Execution contribution for gamma = 9/104"""
        out = run_cmd(["stratified-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json"])
        assert abs(out["categories"]["Execution"]["contribution"] - 9 / 104) < TOL

    def test_gamma_total_matches_full(self):
        """Total score from stratified equals full score = 517/936"""
        out = run_cmd(["stratified-score",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json"])
        assert abs(out["total_score"] - 517 / 936) < TOL


# =============================================================================
# agreement subcommand
# =============================================================================

class TestAgreement:
    def test_overall_kappa(self):
        """Overall Fleiss kappa for 3 judges on paper_gamma = 257/770"""
        out = run_cmd(["agreement",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--predictions-dir", AGREEMENT_DIR])
        assert abs(out["overall_kappa"] - 257 / 770) < TOL

    def test_num_raters(self):
        out = run_cmd(["agreement",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--predictions-dir", AGREEMENT_DIR])
        assert out["num_raters"] == 3

    def test_num_subjects(self):
        out = run_cmd(["agreement",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--predictions-dir", AGREEMENT_DIR])
        assert out["num_subjects"] == 19

    def test_cd_kappa(self):
        """Code Development kappa = 1/55"""
        out = run_cmd(["agreement",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--predictions-dir", AGREEMENT_DIR])
        assert abs(out["per_category"]["Code Development"]["kappa"] - 1 / 55) < TOL

    def test_execution_kappa(self):
        """Execution kappa = 4/9"""
        out = run_cmd(["agreement",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--predictions-dir", AGREEMENT_DIR])
        assert abs(out["per_category"]["Execution"]["kappa"] - 4 / 9) < TOL

    def test_rm_kappa(self):
        """Result Match kappa = -1/44 (worse than chance)"""
        out = run_cmd(["agreement",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--predictions-dir", AGREEMENT_DIR])
        assert abs(out["per_category"]["Result Match"]["kappa"] - (-1 / 44)) < TOL


# =============================================================================
# score-bounds subcommand
# =============================================================================

class TestScoreBounds:
    def test_alpha_rm_bounds(self):
        """Alpha with uncertain=table1,figure1: all RM leaves grade=0, only upward swing"""
        out = run_cmd(["score-bounds",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json",
                       "--uncertain", "table1,figure1"])
        assert abs(out["current_score"] - 0.65) < TOL
        assert abs(out["min_score"] - 0.65) < TOL
        assert abs(out["max_score"] - 0.95) < TOL
        assert abs(out["max_swing"] - 0.3) < TOL

    def test_alpha_cd_bounds(self):
        """Alpha with uncertain=encoder,run_exp1: all grade=1, only downward swing"""
        out = run_cmd(["score-bounds",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json",
                       "--uncertain", "encoder,run_exp1"])
        assert abs(out["current_score"] - 0.65) < TOL
        assert abs(out["min_score"] - 0.5) < TOL
        assert abs(out["max_score"] - 0.65) < TOL
        assert abs(out["max_swing"] - 0.15) < TOL

    def test_alpha_all_cd_bounds(self):
        """Alpha with uncertain=encoder,decoder,training: full CD wing"""
        out = run_cmd(["score-bounds",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json",
                       "--uncertain", "encoder,decoder,training"])
        assert abs(out["current_score"] - 0.65) < TOL
        assert abs(out["min_score"] - 0.05) < TOL
        assert abs(out["max_score"] - 0.65) < TOL
        assert abs(out["max_swing"] - 0.6) < TOL

    def test_alpha_single_leaf(self):
        """Alpha with single uncertain leaf encoder (grade=1, sensitivity=0.1)"""
        out = run_cmd(["score-bounds",
                       "--rubric", f"{RUBRICS_DIR}/paper_alpha.json",
                       "--grades", f"{GRADES_DIR}/paper_alpha.json",
                       "--uncertain", "encoder"])
        assert abs(out["min_score"] - 0.55) < TOL
        assert abs(out["max_score"] - 0.65) < TOL
        assert abs(out["max_swing"] - 0.1) < TOL

    def test_gamma_rm_bounds(self):
        """Gamma with uncertain=all RM leaves: mixed grades"""
        out = run_cmd(["score-bounds",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json",
                       "--uncertain", "row_1,row_2,row_3,table_2,figure_1"])
        assert abs(out["current_score"] - 517 / 936) < TOL
        assert abs(out["min_score"] - 469 / 936) < TOL
        assert abs(out["max_score"] - 757 / 936) < TOL
        assert abs(out["max_swing"] - 4 / 13) < TOL

    def test_gamma_mixed_category_bounds(self):
        """Gamma with uncertain=loss,layer2,run_a: cross-category"""
        out = run_cmd(["score-bounds",
                       "--rubric", f"{RUBRICS_DIR}/paper_gamma.json",
                       "--grades", f"{GRADES_DIR}/paper_gamma.json",
                       "--uncertain", "loss,layer2,run_a"])
        assert abs(out["current_score"] - 517 / 936) < TOL
        assert abs(out["min_score"] - 317 / 936) < TOL
        assert abs(out["max_score"] - 598 / 936) < TOL
        assert abs(out["max_swing"] - 281 / 936) < TOL


# =============================================================================
# analysis pipeline
# =============================================================================

@pytest.fixture(scope="module")
def pipeline_db():
    """Run the pipeline once and return a database connection."""
    if os.path.exists("/app/results.db"):
        os.remove("/app/results.db")
    result = subprocess.run(
        ["bash", "/app/analyze.sh"],
        capture_output=True, text=True, timeout=120,
        cwd="/app"
    )
    if result.returncode != 0:
        pytest.fail(f"Pipeline failed (exit {result.returncode}):\n{result.stderr}")
    conn = sqlite3_mod.connect("/app/results.db")
    yield conn
    conn.close()


class TestPipeline:
    def test_pipeline_script_exists(self):
        assert os.path.exists("/app/analyze.sh"), "analyze.sh not found"

    def test_pipeline_uses_jq(self):
        with open("/app/analyze.sh") as f:
            content = f.read()
        assert "jq" in content, "Pipeline must use jq for JSON processing"

    def test_pipeline_uses_sqlite3(self):
        with open("/app/analyze.sh") as f:
            content = f.read()
        assert "sqlite3" in content, "Pipeline must use sqlite3 for storage"

    def test_scores_table(self, pipeline_db):
        rows = pipeline_db.execute(
            "SELECT paper, leaf_count, score FROM scores ORDER BY paper"
        ).fetchall()
        assert len(rows) == 3
        alpha = next(r for r in rows if r[0] == "paper_alpha")
        assert alpha[1] == 7
        assert abs(alpha[2] - 0.65) < TOL

    def test_stratified_table(self, pipeline_db):
        count = pipeline_db.execute(
            "SELECT COUNT(*) FROM stratified"
        ).fetchone()[0]
        assert count == 9
        row = pipeline_db.execute(
            "SELECT contribution FROM stratified "
            "WHERE paper='paper_alpha' AND category='Code Development'"
        ).fetchone()
        assert row is not None
        assert abs(row[0] - 0.6) < TOL

    def test_optimal_depths_table(self, pipeline_db):
        rows = pipeline_db.execute(
            "SELECT epsilon, depth, max_error FROM optimal_depths ORDER BY epsilon"
        ).fetchall()
        assert len(rows) == 4
        tight = next(r for r in rows if abs(r[0] - 0.01) < 1e-6)
        assert tight[1] == 4
        assert tight[2] <= 0.01 + TOL

    def test_bounds_table(self, pipeline_db):
        rows = pipeline_db.execute(
            "SELECT paper, current_score, min_score, max_score, max_swing "
            "FROM bounds ORDER BY paper"
        ).fetchall()
        assert len(rows) == 3
        alpha = next(r for r in rows if r[0] == "paper_alpha")
        assert abs(alpha[1] - 0.65) < TOL
        assert abs(alpha[2] - 0.65) < TOL
        assert abs(alpha[3] - 0.95) < TOL
        assert abs(alpha[4] - 0.3) < TOL

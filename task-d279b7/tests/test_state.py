
import json
import subprocess
import pytest


def run_analyzer(experiment_file):
    """Run the analyzer and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/dioptra_analyzer.py", experiment_file],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}.\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Analyzer output is not valid JSON: {result.stdout[:500]}")


# ──────────────────────────────────────────────────────────────────────
# Test: simple_pipeline.yaml
# Linear pipeline: load_data → split_data → train_model → evaluate_model
# Edges: load→split ($load_data), split→train ($split_data.train_set),
#        split→eval ($split_data.test_set), train→eval ($train_model)
# ──────────────────────────────────────────────────────────────────────


class TestSimplePipeline:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/experiments/simple_pipeline.yaml")

    def test_num_steps(self):
        assert self.r["num_steps"] == 4

    def test_num_edges(self):
        assert self.r["num_edges"] == 4

    def test_no_cycle(self):
        assert self.r["has_cycle"] is False
        assert self.r["cycle_path"] is None

    def test_topological_order(self):
        assert self.r["topological_order"] == [
            "load_data",
            "split_data",
            "train_model",
            "evaluate_model",
        ]

    def test_step_depths(self):
        assert self.r["step_depths"] == {
            "load_data": 0,
            "split_data": 1,
            "train_model": 2,
            "evaluate_model": 3,
        }

    def test_critical_path(self):
        assert self.r["critical_path"] == [
            "load_data",
            "split_data",
            "train_model",
            "evaluate_model",
        ]
        assert self.r["critical_path_cost"] == 4

    def test_max_parallelism(self):
        assert self.r["max_parallelism"] == 1

    def test_used_params(self):
        used = self.r["global_params_used"]
        for p in ["dataset_path", "learning_rate", "epochs", "batch_size"]:
            assert p in used, f"Expected '{p}' in global_params_used"

    def test_unused_params(self):
        assert "unused_param" in self.r["unused_params"]

    def test_issues_unused_param(self):
        types = [i["type"] for i in self.r["issues"]]
        assert "unused_parameter" in types


# ──────────────────────────────────────────────────────────────────────
# Test: complex_diamond.yaml
# Diamond topology with adversarial ML workflow, 7 steps, explicit deps,
# positional invocation on init_rng, multi-output step (gen_adversarial),
# dotted output references ($gen_adversarial.adversarial_dataset).
# ──────────────────────────────────────────────────────────────────────


class TestComplexDiamond:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/experiments/complex_diamond.yaml")

    def test_num_steps(self):
        assert self.r["num_steps"] == 7

    def test_num_edges(self):
        assert self.r["num_edges"] == 11

    def test_no_cycle(self):
        assert self.r["has_cycle"] is False

    def test_topological_order(self):
        order = self.r["topological_order"]
        assert order == [
            "init_rng",
            "load_data",
            "train_base",
            "gen_adversarial",
            "defend_model",
            "eval_accuracy",
            "eval_robust",
        ]

    def test_step_depths(self):
        assert self.r["step_depths"] == {
            "init_rng": 0,
            "load_data": 1,
            "train_base": 2,
            "gen_adversarial": 3,
            "defend_model": 4,
            "eval_robust": 5,
            "eval_accuracy": 5,
        }

    def test_critical_path(self):
        assert self.r["critical_path"] == [
            "init_rng",
            "load_data",
            "train_base",
            "gen_adversarial",
            "defend_model",
            "eval_accuracy",
        ]
        assert self.r["critical_path_cost"] == 6

    def test_max_parallelism(self):
        assert self.r["max_parallelism"] == 2

    def test_all_params_used(self):
        assert len(self.r["unused_params"]) == 0
        used = set(self.r["global_params_used"])
        assert used == {"seed", "dataset_path", "epsilon", "num_epochs", "defense_type"}

    def test_no_issues(self):
        assert len(self.r["issues"]) == 0


# ──────────────────────────────────────────────────────────────────────
# Test: cyclic_workflow.yaml
# step_a→step_b→step_c→step_a cycle
# ──────────────────────────────────────────────────────────────────────


class TestCyclicWorkflow:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/experiments/cyclic_workflow.yaml")

    def test_has_cycle(self):
        assert self.r["has_cycle"] is True

    def test_cycle_path_contains_all_steps(self):
        cp = self.r["cycle_path"]
        assert cp is not None
        assert len(cp) >= 4  # at least 3 unique + repeat
        # First and last element should be the same (cycle closure)
        assert cp[0] == cp[-1]
        unique = set(cp)
        assert {"step_a", "step_b", "step_c"}.issubset(unique)

    def test_metrics_null_when_cyclic(self):
        assert self.r["topological_order"] is None
        assert self.r["critical_path"] is None
        assert self.r["critical_path_cost"] is None
        assert self.r["max_parallelism"] is None
        assert self.r["step_depths"] is None

    def test_num_steps(self):
        assert self.r["num_steps"] == 3

    def test_num_edges(self):
        assert self.r["num_edges"] == 3

    def test_cycle_issue_reported(self):
        types = [i["type"] for i in self.r["issues"]]
        assert "cycle" in types

    def test_unused_param_still_reported(self):
        assert "threshold" in self.r["unused_params"]


# ──────────────────────────────────────────────────────────────────────
# Test: broken_refs.yaml
# Issues: invalid output ref, unresolvable ref, undefined task, unused param
# ──────────────────────────────────────────────────────────────────────


class TestBrokenRefs:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/experiments/broken_refs.yaml")

    def test_num_steps(self):
        assert self.r["num_steps"] == 3

    def test_no_cycle(self):
        assert self.r["has_cycle"] is False

    def test_edges(self):
        # load_data→train_model (from $load_data.nonexistent_output)
        # train_model→predict (from $train_model)
        assert self.r["num_edges"] == 2

    def test_topological_order(self):
        assert self.r["topological_order"] == [
            "load_data",
            "train_model",
            "predict",
        ]

    def test_step_depths(self):
        assert self.r["step_depths"] == {
            "load_data": 0,
            "train_model": 1,
            "predict": 2,
        }

    def test_critical_path(self):
        assert self.r["critical_path"] == [
            "load_data",
            "train_model",
            "predict",
        ]
        assert self.r["critical_path_cost"] == 3

    def test_issue_invalid_output_reference(self):
        types = [i["type"] for i in self.r["issues"]]
        assert "invalid_output_reference" in types

    def test_issue_unresolvable_reference(self):
        types = [i["type"] for i in self.r["issues"]]
        assert "unresolvable_reference" in types
        # Find the specific issue
        unresolvable = [
            i for i in self.r["issues"] if i["type"] == "unresolvable_reference"
        ]
        refs = [i.get("reference", "") for i in unresolvable]
        assert any("missing_reference" in r for r in refs)

    def test_issue_undefined_task(self):
        types = [i["type"] for i in self.r["issues"]]
        assert "undefined_task" in types
        undef = [i for i in self.r["issues"] if i["type"] == "undefined_task"]
        assert any(i.get("task") == "nonexistent_task" for i in undef)

    def test_issue_unused_parameter(self):
        assert "orphan_param" in self.r["unused_params"]

    def test_used_params(self):
        used = self.r["global_params_used"]
        assert "dataset_path" in used
        assert "learning_rate" in used


# ──────────────────────────────────────────────────────────────────────
# Test: mixed_invocations.yaml
# Tests positional ($seed), keyword, mixed (task: build_model),
# string dependencies, escaped $$, dotted refs ($split_data.train)
# ──────────────────────────────────────────────────────────────────────


class TestMixedInvocations:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/experiments/mixed_invocations.yaml")

    def test_num_steps(self):
        assert self.r["num_steps"] == 6

    def test_num_edges(self):
        assert self.r["num_edges"] == 7

    def test_no_cycle(self):
        assert self.r["has_cycle"] is False

    def test_topological_order(self):
        order = self.r["topological_order"]
        assert order == [
            "init",
            "create_model",
            "load_data",
            "split_data",
            "train_model",
            "eval_model",
        ]

    def test_step_depths(self):
        assert self.r["step_depths"] == {
            "init": 0,
            "create_model": 1,
            "load_data": 1,
            "split_data": 2,
            "train_model": 3,
            "eval_model": 4,
        }

    def test_critical_path(self):
        assert self.r["critical_path"] == [
            "init",
            "load_data",
            "split_data",
            "train_model",
            "eval_model",
        ]
        assert self.r["critical_path_cost"] == 5

    def test_max_parallelism(self):
        # Depth 1 has create_model and load_data
        assert self.r["max_parallelism"] == 2

    def test_used_params(self):
        used = set(self.r["global_params_used"])
        assert used == {"seed", "data_dir", "model_type"}

    def test_unused_escaped_ref(self):
        assert "escaped_ref" in self.r["unused_params"]

    def test_escaped_dollar_not_treated_as_ref(self):
        # $$literal_dollar should NOT create a dependency or be flagged
        types = [i["type"] for i in self.r["issues"]]
        # The only issue should be unused_parameter for escaped_ref
        for issue in self.r["issues"]:
            if issue["type"] == "unresolvable_reference":
                assert "literal_dollar" not in issue.get("reference", "")

    def test_string_dependency_handled(self):
        # load_data has dependencies: init (string, not list)
        # This should create an edge init→load_data
        order = self.r["topological_order"]
        assert order.index("init") < order.index("load_data")

    def test_mixed_invocation_parsed(self):
        # create_model uses mixed invocation with task: build_model
        # $model_type should be detected as used
        assert "model_type" in self.r["global_params_used"]


# ──────────────────────────────────────────────────────────────────────
# Test: Output format structure
# ──────────────────────────────────────────────────────────────────────


class TestOutputFormat:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analyzer("/app/experiments/simple_pipeline.yaml")

    def test_required_fields_present(self):
        required = [
            "file",
            "num_steps",
            "num_edges",
            "has_cycle",
            "cycle_path",
            "topological_order",
            "critical_path",
            "critical_path_cost",
            "max_parallelism",
            "step_depths",
            "global_params_used",
            "unused_params",
            "issues",
        ]
        for field in required:
            assert field in self.r, f"Missing required field: {field}"

    def test_field_types(self):
        assert isinstance(self.r["num_steps"], int)
        assert isinstance(self.r["num_edges"], int)
        assert isinstance(self.r["has_cycle"], bool)
        assert isinstance(self.r["topological_order"], list)
        assert isinstance(self.r["critical_path"], list)
        assert isinstance(self.r["critical_path_cost"], int)
        assert isinstance(self.r["max_parallelism"], int)
        assert isinstance(self.r["step_depths"], dict)
        assert isinstance(self.r["global_params_used"], list)
        assert isinstance(self.r["unused_params"], list)
        assert isinstance(self.r["issues"], list)

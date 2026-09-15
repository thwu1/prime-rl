
import hashlib
import json
import subprocess
import pytest

CONFIG_PATH = "/app/planner_config.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def compute_digest(execution_plan, salt):
    entries = "|".join(
        f"{t['node_id']}:{t['task_index']}" for t in execution_plan
    )
    return hashlib.sha256((salt + entries).encode()).hexdigest()[:16]


def run_planner(workflow_path, params=None):
    cmd = ["python3", "/app/planner.py", workflow_path]
    if params:
        for k, v in params.items():
            cmd.extend(["--param", f"{k}={v}"])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"Planner exited {result.returncode}: {result.stderr}"
    return json.loads(result.stdout)


class TestConfigIntegration:
    def test_plan_format_version(self):
        config = load_config()
        plan = run_planner("/app/workflows/simple.yaml")
        assert plan["plan_format_version"] == config["plan_format_version"]

    def test_plan_digest_valid(self):
        config = load_config()
        plan = run_planner("/app/workflows/simple.yaml")
        expected = compute_digest(plan["execution_plan"], config["digest_salt"])
        assert plan["plan_digest"] == expected

    def test_plan_digest_invalid(self):
        config = load_config()
        plan = run_planner("/app/workflows/cyclic.yaml")
        expected = hashlib.sha256(config["digest_salt"].encode()).hexdigest()[:16]
        assert plan["plan_digest"] == expected

    def test_plan_digest_complex(self):
        config = load_config()
        plan = run_planner("/app/workflows/complex.yaml")
        expected = compute_digest(plan["execution_plan"], config["digest_salt"])
        assert plan["plan_digest"] == expected

    def test_priority_ordering(self):
        plan = run_planner("/app/workflows/priority_test.yaml")
        assert plan["valid"] is True
        ids = [t["node_id"] for t in plan["execution_plan"]]
        assert ids[0] == "root"
        assert ids[-1] == "finish"
        # Priority weights from config: analyze=10, build=50, deploy=80, cleanup=95
        # Pure alphabetical would give: analyze, build, cleanup, deploy
        # Priority ordering gives: analyze, build, deploy, cleanup
        assert ids[1:5] == ["analyze", "build", "deploy", "cleanup"]


class TestDAGOrdering:
    def test_simple_linear(self):
        plan = run_planner("/app/workflows/simple.yaml")
        assert plan["valid"] is True
        assert len(plan["errors"]) == 0
        assert len(plan["execution_plan"]) == 3
        ids = [t["node_id"] for t in plan["execution_plan"]]
        assert ids == ["setup", "build", "test"]
        for task in plan["execution_plan"]:
            assert len(task["steps"]) == 1
            assert task["steps"][0]["will_execute"] is True
            assert task["steps"][0]["type"] == "run"
            assert "resolved_run" in task["steps"][0]

    def test_diamond_dag(self):
        plan = run_planner("/app/workflows/diamond.yaml")
        assert plan["valid"] is True
        ids = [t["node_id"] for t in plan["execution_plan"]]
        assert ids[0] == "start"
        assert ids[-1] == "merge"
        # left and right both use _default priority, so alphabetical tie-break
        assert ids[1] == "left"
        assert ids[2] == "right"


class TestCycleDetection:
    def test_three_node_cycle(self):
        plan = run_planner("/app/workflows/cyclic.yaml")
        assert plan["valid"] is False
        assert len(plan["execution_plan"]) == 0
        assert any("cycl" in e.lower() for e in plan["errors"])

    def test_self_dependency(self):
        plan = run_planner("/app/workflows/self_dep.yaml")
        assert plan["valid"] is False
        assert len(plan["execution_plan"]) == 0
        assert any("cycl" in e.lower() or "self" in e.lower() for e in plan["errors"])


class TestMatrixExpansion:
    def test_inline_values(self):
        plan = run_planner("/app/workflows/matrix_inline.yaml")
        assert plan["valid"] is True
        assert len(plan["execution_plan"]) == 2
        envs = [t["matrix_values"]["env"] for t in plan["execution_plan"]]
        assert envs == ["staging", "prod"]
        regions = [t["matrix_values"]["region"] for t in plan["execution_plan"]]
        assert regions == ["us-east", "eu-west"]
        for task in plan["execution_plan"]:
            step = task["steps"][0]
            env = task["matrix_values"]["env"]
            region = task["matrix_values"]["region"]
            assert f"--env={env}" in step["resolved_run"]
            assert f"--region={region}" in step["resolved_run"]


class TestConditionals:
    def test_default_params(self):
        plan = run_planner("/app/workflows/conditional.yaml")
        assert plan["valid"] is True
        steps = plan["execution_plan"][0]["steps"]
        ts_step = next(s for s in steps if s["name"] == "Run TypeScript transform")
        js_step = next(s for s in steps if s["name"] == "Run JavaScript transform")
        lint_step = next(s for s in steps if s["name"] == "Lint")
        assert ts_step["will_execute"] is True
        assert js_step["will_execute"] is False
        assert lint_step["will_execute"] is True

    def test_override_params(self):
        plan = run_planner(
            "/app/workflows/conditional.yaml",
            params={"language": "javascript", "run_lint": "false"},
        )
        steps = plan["execution_plan"][0]["steps"]
        ts_step = next(s for s in steps if s["name"] == "Run TypeScript transform")
        js_step = next(s for s in steps if s["name"] == "Run JavaScript transform")
        lint_step = next(s for s in steps if s["name"] == "Lint")
        assert ts_step["will_execute"] is False
        assert js_step["will_execute"] is True
        assert lint_step["will_execute"] is False


class TestStatefulMatrix:
    def test_state_mutations_feed_matrix(self):
        plan = run_planner("/app/workflows/stateful.yaml")
        assert plan["valid"] is True
        assert plan["execution_plan"][0]["node_id"] == "discover"
        migrate_tasks = [t for t in plan["execution_plan"] if t["node_id"] == "migrate"]
        assert len(migrate_tasks) == 3
        teams = [t["matrix_values"]["name"] for t in migrate_tasks]
        assert teams == ["platform", "mobile", "web"]
        for task in migrate_tasks:
            step = task["steps"][0]
            name = task["matrix_values"]["name"]
            path = task["matrix_values"]["path"]
            assert f"--team={name}" in step["resolved_run"]
            assert f"--path={path}" in step["resolved_run"]
        assert len(plan["final_state"]["teams"]) == 3


class TestValidation:
    def test_invalid_dependency_reference(self):
        plan = run_planner("/app/workflows/invalid_ref.yaml")
        assert plan["valid"] is False
        assert any("nonexistent" in e.lower() for e in plan["errors"])

    def test_missing_nodes(self):
        plan = run_planner("/app/workflows/no_nodes.yaml")
        assert plan["valid"] is False
        assert any("nodes" in e.lower() for e in plan["errors"])


class TestComplexWorkflow:
    def test_full_integration(self):
        plan = run_planner("/app/workflows/complex.yaml")
        assert plan["valid"] is True
        assert plan["execution_plan"][0]["node_id"] == "analyze"
        transform_tasks = [
            t for t in plan["execution_plan"] if t["node_id"] == "transform"
        ]
        assert len(transform_tasks) == 3
        shard_ids = [t["matrix_values"]["shard_id"] for t in transform_tasks]
        assert shard_ids == ["s1", "s2", "s3"]
        for task in transform_tasks:
            jssg_step = next(
                s for s in task["steps"] if s["name"] == "Apply JSSG transform"
            )
            assert jssg_step["type"] == "js-ast-grep"
            assert jssg_step["will_execute"] is True
            assert "resolved_run" not in jssg_step
            run_step = next(s for s in task["steps"] if s["name"] == "Apply codemod")
            assert run_step["will_execute"] is True
            assert "--lib=react" in run_step["resolved_run"]
            sid = task["matrix_values"]["shard_id"]
            assert f"--shard={sid}" in run_step["resolved_run"]
            dry_step = next(
                s for s in task["steps"] if s["name"] == "Apply dry-run check"
            )
            assert dry_step["will_execute"] is False
        assert plan["execution_plan"][-1]["node_id"] == "report"
        report_step = plan["execution_plan"][-1]["steps"][0]
        assert "--lib=react" in report_step["resolved_run"]

    def test_dry_run_override(self):
        plan = run_planner(
            "/app/workflows/complex.yaml", params={"dry_run": "true"}
        )
        transform_tasks = [
            t for t in plan["execution_plan"] if t["node_id"] == "transform"
        ]
        for task in transform_tasks:
            dry_step = next(
                s for s in task["steps"] if s["name"] == "Apply dry-run check"
            )
            assert dry_step["will_execute"] is True


class TestExpressions:
    def test_multiple_expressions_and_override(self):
        plan = run_planner(
            "/app/workflows/expressions.yaml", params={"name": "earth"}
        )
        steps = plan["execution_plan"][0]["steps"]
        assert steps[0]["resolved_run"] == "echo hello earth"
        assert steps[1]["resolved_run"] == "deploy --tag=hello-earth --verbose"

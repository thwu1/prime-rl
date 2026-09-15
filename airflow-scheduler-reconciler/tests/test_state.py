
import json
import os
import pytest

REPORT_PATH = "/app/anomaly_report.json"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


def test_report_structure(report):
    """Report has required top-level keys with correct types."""
    assert "anomalies" in report, "Missing 'anomalies' key"
    assert "summary" in report, "Missing 'summary' key"
    assert isinstance(report["anomalies"], list), "'anomalies' must be a list"
    assert "total" in report["summary"], "Missing 'total' in summary"
    assert "by_type" in report["summary"], "Missing 'by_type' in summary"
    assert isinstance(report["summary"]["by_type"], dict), "'by_type' must be a dict"


def test_anomaly_entry_structure(report):
    """Each anomaly entry has the required fields."""
    required_keys = {"type", "dag_id", "description", "severity"}
    for i, anomaly in enumerate(report["anomalies"]):
        for key in required_keys:
            assert key in anomaly, f"Anomaly {i} missing key '{key}'"
        assert anomaly["severity"] in ("critical", "high", "medium", "low"), (
            f"Anomaly {i} has invalid severity: {anomaly['severity']}"
        )


def test_total_anomaly_count(report):
    """Exactly 7 anomalies should be detected."""
    assert report["summary"]["total"] == 7, (
        f"Expected 7 total anomalies, got {report['summary']['total']}"
    )
    assert len(report["anomalies"]) == 7, (
        f"Expected 7 anomaly entries, got {len(report['anomalies'])}"
    )


def test_zombie_task_count(report):
    """Two zombie tasks should be detected."""
    zombies = [a for a in report["anomalies"] if a["type"] == "zombie_task"]
    assert len(zombies) == 2, f"Expected 2 zombie_task anomalies, got {len(zombies)}"


def test_zombie_etl_pipeline_load_data(report):
    """Zombie: etl_pipeline.load_data on worker-epsilon with stale heartbeat."""
    zombies = [a for a in report["anomalies"] if a["type"] == "zombie_task"]
    etl_zombies = [z for z in zombies if z["dag_id"] == "etl_pipeline"]
    assert len(etl_zombies) == 1, "Expected exactly 1 zombie in etl_pipeline"
    assert etl_zombies[0]["task_id"] == "load_data", (
        f"Expected zombie task_id 'load_data', got '{etl_zombies[0].get('task_id')}'"
    )


def test_zombie_report_generator_render(report):
    """Zombie: report_generator.render_report on worker-gamma with stale heartbeat."""
    zombies = [a for a in report["anomalies"] if a["type"] == "zombie_task"]
    rg_zombies = [z for z in zombies if z["dag_id"] == "report_generator"]
    assert len(rg_zombies) == 1, "Expected exactly 1 zombie in report_generator"
    assert rg_zombies[0]["task_id"] == "render_report", (
        f"Expected zombie task_id 'render_report', got '{rg_zombies[0].get('task_id')}'"
    )


def test_missed_dataset_trigger(report):
    """One missed dataset trigger for ml_training."""
    missed = [a for a in report["anomalies"] if a["type"] == "missed_dataset_trigger"]
    assert len(missed) == 1, f"Expected 1 missed_dataset_trigger, got {len(missed)}"
    assert missed[0]["dag_id"] == "ml_training", (
        f"Expected dag_id 'ml_training', got '{missed[0]['dag_id']}'"
    )


def test_incorrect_data_interval(report):
    """One incorrect data interval for report_generator Jan 17 run."""
    incorrect = [a for a in report["anomalies"] if a["type"] == "incorrect_data_interval"]
    assert len(incorrect) == 1, f"Expected 1 incorrect_data_interval, got {len(incorrect)}"
    assert incorrect[0]["dag_id"] == "report_generator", (
        f"Expected dag_id 'report_generator', got '{incorrect[0]['dag_id']}'"
    )
    run_id = incorrect[0].get("run_id", "")
    assert run_id is not None and "scheduled__2024-01-17" in run_id, (
        f"Expected run_id containing 'scheduled__2024-01-17', got '{run_id}'"
    )


def test_stuck_retry(report):
    """One stuck retry for data_quality.check_completeness."""
    stuck = [a for a in report["anomalies"] if a["type"] == "stuck_retry"]
    assert len(stuck) == 1, f"Expected 1 stuck_retry, got {len(stuck)}"
    assert stuck[0]["dag_id"] == "data_quality", (
        f"Expected dag_id 'data_quality', got '{stuck[0]['dag_id']}'"
    )
    assert stuck[0]["task_id"] == "check_completeness", (
        f"Expected task_id 'check_completeness', got '{stuck[0].get('task_id')}'"
    )


def test_duplicate_scheduling(report):
    """One duplicate scheduling for etl_pipeline.extract_data."""
    dupes = [a for a in report["anomalies"] if a["type"] == "duplicate_scheduling"]
    assert len(dupes) == 1, f"Expected 1 duplicate_scheduling, got {len(dupes)}"
    assert dupes[0]["dag_id"] == "etl_pipeline", (
        f"Expected dag_id 'etl_pipeline', got '{dupes[0]['dag_id']}'"
    )
    assert dupes[0]["task_id"] == "extract_data", (
        f"Expected task_id 'extract_data', got '{dupes[0].get('task_id')}'"
    )


def test_dependency_violation(report):
    """One dependency violation: ml_training.evaluate_model succeeded despite train_model failing."""
    violations = [a for a in report["anomalies"] if a["type"] == "dependency_violation"]
    assert len(violations) == 1, f"Expected 1 dependency_violation, got {len(violations)}"
    assert violations[0]["dag_id"] == "ml_training", (
        f"Expected dag_id 'ml_training', got '{violations[0]['dag_id']}'"
    )
    assert violations[0]["task_id"] == "evaluate_model", (
        f"Expected task_id 'evaluate_model', got '{violations[0].get('task_id')}'"
    )


def test_summary_by_type(report):
    """Summary by_type counts match the anomaly list."""
    by_type = report["summary"]["by_type"]
    assert by_type.get("zombie_task") == 2, (
        f"Expected by_type['zombie_task']=2, got {by_type.get('zombie_task')}"
    )
    assert by_type.get("missed_dataset_trigger") == 1, (
        f"Expected by_type['missed_dataset_trigger']=1, got {by_type.get('missed_dataset_trigger')}"
    )
    assert by_type.get("incorrect_data_interval") == 1, (
        f"Expected by_type['incorrect_data_interval']=1, got {by_type.get('incorrect_data_interval')}"
    )
    assert by_type.get("stuck_retry") == 1, (
        f"Expected by_type['stuck_retry']=1, got {by_type.get('stuck_retry')}"
    )
    assert by_type.get("duplicate_scheduling") == 1, (
        f"Expected by_type['duplicate_scheduling']=1, got {by_type.get('duplicate_scheduling')}"
    )
    assert by_type.get("dependency_violation") == 1, (
        f"Expected by_type['dependency_violation']=1, got {by_type.get('dependency_violation')}"
    )


def test_summary_total_consistent(report):
    """Summary total matches the sum of by_type counts."""
    total = report["summary"]["total"]
    by_type_sum = sum(report["summary"]["by_type"].values())
    assert total == by_type_sum, (
        f"Summary total ({total}) != sum of by_type counts ({by_type_sum})"
    )

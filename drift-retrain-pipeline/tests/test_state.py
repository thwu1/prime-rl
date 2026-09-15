
import json
import os
import pytest
import yaml
import mlflow
import mlflow.tracking


# ──────────────────── Drift Report Tests ────────────────────


class TestDriftReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        assert os.path.exists('/app/output/drift_report.json'), \
            "drift_report.json must exist in /app/output/"
        with open('/app/output/drift_report.json') as f:
            self.report = json.load(f)

    def test_top_level_keys(self):
        assert 'features' in self.report
        assert 'drifted_features' in self.report
        assert 'n_drifted' in self.report
        assert isinstance(self.report['drifted_features'], list)
        assert isinstance(self.report['n_drifted'], int)
        assert self.report['n_drifted'] == len(self.report['drifted_features'])

    def test_all_features_present(self):
        for feat in ['temperature', 'pressure', 'vibration', 'humidity', 'speed']:
            assert feat in self.report['features'], f"Missing feature: {feat}"

    def test_feature_statistics_structure(self):
        for feat_name, feat_data in self.report['features'].items():
            assert 'ks_statistic' in feat_data, f"{feat_name}: missing ks_statistic"
            assert 'ks_pvalue' in feat_data, f"{feat_name}: missing ks_pvalue"
            assert 'psi' in feat_data, f"{feat_name}: missing psi"
            assert 'kde_overlap' in feat_data, f"{feat_name}: missing kde_overlap"
            assert 'is_drifted' in feat_data, f"{feat_name}: missing is_drifted"
            assert 0 <= feat_data['ks_statistic'] <= 1
            assert 0 <= feat_data['ks_pvalue'] <= 1
            assert feat_data['psi'] >= 0
            assert 0 <= feat_data['kde_overlap'] <= 1.01

    def test_temperature_is_drifted(self):
        assert self.report['features']['temperature']['is_drifted'] is True, \
            "temperature should be detected as drifted"

    def test_vibration_is_drifted(self):
        assert self.report['features']['vibration']['is_drifted'] is True, \
            "vibration should be detected as drifted"

    def test_pressure_not_drifted(self):
        assert self.report['features']['pressure']['is_drifted'] is False, \
            "pressure should NOT be detected as drifted"

    def test_humidity_not_drifted(self):
        assert self.report['features']['humidity']['is_drifted'] is False, \
            "humidity should NOT be detected as drifted"

    def test_temperature_statistics_ranges(self):
        t = self.report['features']['temperature']
        assert t['ks_pvalue'] < 0.001, \
            f"temperature KS p-value should be very small, got {t['ks_pvalue']}"
        assert t['psi'] > 0.5, \
            f"temperature PSI should be large (>0.5), got {t['psi']}"
        assert t['kde_overlap'] < 0.5, \
            f"temperature KDE overlap should be small (<0.5), got {t['kde_overlap']}"

    def test_vibration_statistics_ranges(self):
        v = self.report['features']['vibration']
        assert v['ks_pvalue'] < 0.001, \
            f"vibration KS p-value should be very small, got {v['ks_pvalue']}"
        assert v['psi'] > 0.2, \
            f"vibration PSI should exceed threshold, got {v['psi']}"
        assert v['kde_overlap'] < 0.7, \
            f"vibration KDE overlap should be below threshold, got {v['kde_overlap']}"

    def test_pressure_statistics_ranges(self):
        p = self.report['features']['pressure']
        assert p['ks_pvalue'] > 0.01, \
            f"pressure KS p-value should be large, got {p['ks_pvalue']}"
        assert p['psi'] < 0.15, \
            f"pressure PSI should be small, got {p['psi']}"
        assert p['kde_overlap'] > 0.75, \
            f"pressure KDE overlap should be high, got {p['kde_overlap']}"

    def test_at_least_two_drifted(self):
        assert self.report['n_drifted'] >= 2, \
            f"Should detect at least 2 drifted features, got {self.report['n_drifted']}"


# ──────────────────── MLflow Experiment Tests ────────────────────


class TestMLflowExperiment:
    @pytest.fixture(autouse=True)
    def setup_mlflow(self):
        mlflow.set_tracking_uri('file:///app/mlruns')
        self.experiment = mlflow.get_experiment_by_name('predictive_maintenance')

    def test_experiment_exists(self):
        assert self.experiment is not None, \
            "predictive_maintenance experiment should exist in MLflow"

    def test_has_sweep_runs(self):
        runs = mlflow.search_runs(
            experiment_ids=[self.experiment.experiment_id]
        )
        # Baseline + at least several sweep runs
        assert len(runs) >= 6, \
            f"Expected at least 6 MLflow runs (1 baseline + sweep), found {len(runs)}"

    def test_sweep_runs_have_metrics(self):
        runs = mlflow.search_runs(
            experiment_ids=[self.experiment.experiment_id]
        )
        # Exclude the baseline run
        baseline_id = open('/app/baseline_run_id.txt').read().strip()
        sweep_runs = runs[runs['run_id'] != baseline_id]
        assert len(sweep_runs) > 0, "Should have sweep runs beyond the baseline"

        # Check that at least some sweep runs have F1-related metrics
        has_f1 = False
        for _, run in sweep_runs.iterrows():
            if (run.get('metrics.test_f1') is not None and
                    not (isinstance(run.get('metrics.test_f1'), float) and
                         run.get('metrics.test_f1') != run.get('metrics.test_f1'))):
                has_f1 = True
                break
            if (run.get('metrics.cv_f1_mean') is not None and
                    not (isinstance(run.get('metrics.cv_f1_mean'), float) and
                         run.get('metrics.cv_f1_mean') != run.get('metrics.cv_f1_mean'))):
                has_f1 = True
                break
        assert has_f1, "Sweep runs should have F1-related metrics logged"

    def test_sweep_runs_have_params(self):
        runs = mlflow.search_runs(
            experiment_ids=[self.experiment.experiment_id]
        )
        baseline_id = open('/app/baseline_run_id.txt').read().strip()
        sweep_runs = runs[runs['run_id'] != baseline_id]

        # Check that sweep runs have hyperparameter params logged
        has_params = False
        for _, run in sweep_runs.iterrows():
            if run.get('params.n_estimators') is not None:
                has_params = True
                break
        assert has_params, "Sweep runs should have hyperparameters logged as params"


# ──────────────────── Evaluation Report Tests ────────────────────


class TestEvaluationReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        assert os.path.exists('/app/output/evaluation_report.json'), \
            "evaluation_report.json must exist in /app/output/"
        with open('/app/output/evaluation_report.json') as f:
            self.report = json.load(f)

    def test_top_level_keys(self):
        assert 'baseline' in self.report
        assert 'candidate' in self.report
        assert 'comparison' in self.report

    def test_baseline_metrics_structure(self):
        b = self.report['baseline']
        assert 'metrics' in b
        for m in ['f1_score', 'precision', 'recall', 'accuracy']:
            assert m in b['metrics'], f"Baseline missing metric: {m}"
            assert 0 <= b['metrics'][m] <= 1, f"Baseline {m} out of range"

    def test_candidate_metrics_structure(self):
        c = self.report['candidate']
        assert 'metrics' in c
        for m in ['f1_score', 'precision', 'recall', 'accuracy']:
            assert m in c['metrics'], f"Candidate missing metric: {m}"
            assert 0 <= c['metrics'][m] <= 1, f"Candidate {m} out of range"

    def test_fairness_metrics_present(self):
        for model_key in ['baseline', 'candidate']:
            assert 'fairness' in self.report[model_key], \
                f"{model_key} missing fairness metrics"
            f = self.report[model_key]['fairness']
            assert 'equalized_odds_gap' in f, \
                f"{model_key} missing equalized_odds_gap"
            gap = f['equalized_odds_gap']
            assert 0 <= gap <= 1, \
                f"{model_key} equalized_odds_gap should be in [0,1], got {gap}"

    def test_comparison_has_improvement(self):
        assert 'f1_improvement_pct' in self.report['comparison']
        imp = self.report['comparison']['f1_improvement_pct']
        assert isinstance(imp, (int, float))

    def test_candidate_f1_not_terrible(self):
        """Candidate trained on combined data should achieve reasonable F1."""
        c_f1 = self.report['candidate']['metrics']['f1_score']
        assert c_f1 > 0.5, f"Candidate F1 should be >0.5, got {c_f1}"

    def test_candidate_not_worse_than_baseline(self):
        """Retraining on combined data should not degrade performance."""
        b_f1 = self.report['baseline']['metrics']['f1_score']
        c_f1 = self.report['candidate']['metrics']['f1_score']
        assert c_f1 >= b_f1 - 0.05, \
            f"Candidate F1 ({c_f1:.4f}) should not be much worse than baseline ({b_f1:.4f})"


# ──────────────────── Deployment Plan Tests ────────────────────


class TestDeploymentPlan:
    @pytest.fixture(autouse=True)
    def load_data(self):
        assert os.path.exists('/app/output/deployment_plan.json'), \
            "deployment_plan.json must exist in /app/output/"
        with open('/app/output/deployment_plan.json') as f:
            self.plan = json.load(f)
        with open('/app/output/evaluation_report.json') as f:
            self.eval_report = json.load(f)
        with open('/app/config.yaml') as f:
            self.config = yaml.safe_load(f)

    def test_decision_field_valid(self):
        assert 'decision' in self.plan
        assert self.plan['decision'] in (
            'immediate', 'gradual', 'no_rollout', 'blocked', 'no_action'
        ), f"Invalid decision: {self.plan['decision']}"

    def test_reason_field_present(self):
        assert 'reason' in self.plan
        assert isinstance(self.plan['reason'], str)
        assert len(self.plan['reason']) > 0

    def test_decision_consistency_with_evaluation(self):
        """The deployment decision must follow the rules in config."""
        candidate_gap = self.eval_report['candidate']['fairness']['equalized_odds_gap']
        baseline_gap = self.eval_report['baseline']['fairness']['equalized_odds_gap']
        f1_imp = self.eval_report['comparison']['f1_improvement_pct']
        decision = self.plan['decision']
        rules = self.config['deployment']['rollout_rules']
        max_gap = self.config['evaluation']['fairness']['max_allowed_gap']

        fairness_degraded = (candidate_gap > max_gap or
                             candidate_gap > baseline_gap)
        perf_regressed = f1_imp < 0

        if rules['block_on_fairness_degradation'] and fairness_degraded:
            expected = 'blocked'
        elif rules['block_on_performance_regression'] and perf_regressed:
            expected = 'blocked'
        elif f1_imp >= rules['immediate_threshold_pct']:
            expected = 'immediate'
        elif f1_imp >= rules['gradual_threshold_pct']:
            expected = 'gradual'
        else:
            expected = 'no_rollout'

        assert decision == expected, (
            f"Expected '{expected}' but got '{decision}' "
            f"(f1_imp={f1_imp:.2f}%, candidate_gap={candidate_gap:.4f}, "
            f"baseline_gap={baseline_gap:.4f})"
        )

    def test_rollout_schedule_for_immediate(self):
        if self.plan['decision'] != 'immediate':
            pytest.skip("Not an immediate rollout")
        schedule = self.plan.get('rollout_schedule')
        assert schedule is not None, "Immediate rollout must have a schedule"
        assert len(schedule) >= 1
        assert schedule[-1]['traffic_pct'] == 100

    def test_rollout_schedule_for_gradual(self):
        if self.plan['decision'] != 'gradual':
            pytest.skip("Not a gradual rollout")
        schedule = self.plan.get('rollout_schedule')
        assert schedule is not None, "Gradual rollout must have a schedule"
        assert len(schedule) >= 2, "Gradual rollout should have multiple stages"
        # Traffic should be monotonically increasing
        for i in range(1, len(schedule)):
            assert schedule[i]['traffic_pct'] > schedule[i - 1]['traffic_pct'], \
                "Traffic percentages must be monotonically increasing"
        assert schedule[-1]['traffic_pct'] == 100, \
            "Final stage must reach 100% traffic"

    def test_model_registered_if_deploying(self):
        if self.plan['decision'] not in ('immediate', 'gradual'):
            pytest.skip("No deployment, skipping registration check")
        mlflow.set_tracking_uri('file:///app/mlruns')
        client = mlflow.tracking.MlflowClient()
        versions = client.search_model_versions("name='predictive_maintenance_model'")
        assert len(versions) >= 2, (
            f"Should have at least 2 model versions (baseline + candidate), "
            f"found {len(versions)}"
        )

    def test_no_rollout_schedule_when_blocked(self):
        if self.plan['decision'] not in ('blocked', 'no_rollout', 'no_action'):
            pytest.skip("Deployment is happening, not testing blocked path")
        schedule = self.plan.get('rollout_schedule')
        assert schedule is None, \
            "Blocked/no-rollout should have no rollout schedule"

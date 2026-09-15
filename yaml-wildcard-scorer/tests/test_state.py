import json
import os
import pytest
from fractions import Fraction


REPORT_PATH = "/app/output/drift_report.json"

# Expected scores computed from hand-verified leaf counts.
#
# alpha/Deployment: 15 ref leaves (2 WC), 15 cand leaves.
#   K8s quantity matches: 256Mi==268435456, 250m==0.25, 512Mi==536870912, 500m==0.5
#   Protocol defaulting: TCP injected on candidate side
#   Mismatch: image myapp:v1.2.0 != myapp:v1.3.0
#   I=14, U=16, Score=14/16=7/8
#
# alpha/ConfigMap: 6 ref leaves (1 WC), 7 cand leaves.
#   Mismatches: log_level info!=debug, cache_ttl 300!=600. Extra cand: feature_flags
#   I=4, U=9, Score=4/9
#
# beta/Deployment: 16 ref leaves (2 WC), 14 cand leaves.
#   WC: name, annotation revision. Mismatch: env value production!=staging.
#   Extra ref: resources.requests.memory, resources.requests.cpu (not in desired)
#   I=13, U=17, Score=13/17
#
# beta/ConfigMap: 7 ref leaves (0 WC), 6 cand leaves.
#   Extra ref: database_url. All others match.
#   I=6, U=7, Score=6/7
#
# gamma/Deployment: 12 ref leaves (0 WC), 11 cand leaves.
#   Extra ref: metadata.labels.version. Protocol defaulting matches.
#   I=11, U=12, Score=11/12
#
# gamma/ConfigMap: 7 ref leaves (0 WC), 7 cand leaves.
#   Type coercion: enable_metrics True (bool) != "true" (str)
#   I=6, U=8, Score=6/8=3/4

EXPECTED_SCORES = {
    "alpha": {
        "apps/v1/Deployment/alpha-webapp": Fraction(14, 16),
        "v1/ConfigMap/alpha-app-config": Fraction(4, 9),
    },
    "beta": {
        "apps/v1/Deployment/beta-webapp": Fraction(13, 17),
        "v1/ConfigMap/beta-app-config": Fraction(6, 7),
    },
    "gamma": {
        "apps/v1/Deployment/gamma-webapp": Fraction(11, 12),
        "v1/ConfigMap/gamma-app-config": Fraction(6, 8),
    },
}

EXPECTED_ENV_MEANS = {}
for env, resources in EXPECTED_SCORES.items():
    vals = list(resources.values())
    EXPECTED_ENV_MEANS[env] = sum(vals) / len(vals)

ALL_SCORES = []
for resources in EXPECTED_SCORES.values():
    ALL_SCORES.extend(resources.values())
EXPECTED_AGGREGATE = sum(ALL_SCORES) / len(ALL_SCORES)


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


class TestOutputExists:
    def test_file_exists(self):
        assert os.path.exists(REPORT_PATH), \
            f"Output file {REPORT_PATH} not found"

    def test_valid_json(self):
        data = load_report()
        assert isinstance(data, dict)


class TestOutputStructure:
    def test_has_environments(self):
        data = load_report()
        assert "environments" in data, "Missing 'environments' key"
        assert isinstance(data["environments"], dict)

    def test_has_aggregate_mean(self):
        data = load_report()
        assert "aggregate_mean" in data, "Missing 'aggregate_mean' key"
        assert isinstance(data["aggregate_mean"], (int, float))

    def test_all_environments_present(self):
        data = load_report()
        for env_name in EXPECTED_SCORES:
            assert env_name in data["environments"], \
                f"Missing environment '{env_name}'"

    def test_environment_structure(self):
        data = load_report()
        for env_name in EXPECTED_SCORES:
            env = data["environments"][env_name]
            assert "resources" in env, \
                f"Missing 'resources' in environment '{env_name}'"
            assert "mean" in env, \
                f"Missing 'mean' in environment '{env_name}'"

    def test_all_resources_present(self):
        data = load_report()
        for env_name, expected_resources in EXPECTED_SCORES.items():
            actual = data["environments"][env_name]["resources"]
            for rid in expected_resources:
                assert rid in actual, \
                    f"Missing resource '{rid}' in environment '{env_name}'"

    def test_scores_in_valid_range(self):
        data = load_report()
        for env_name, env_data in data["environments"].items():
            for rid, score in env_data["resources"].items():
                assert 0.0 <= score <= 1.0, \
                    f"Score for {env_name}/{rid} out of range: {score}"
            assert 0.0 <= env_data["mean"] <= 1.0, \
                f"Mean for {env_name} out of range: {env_data['mean']}"
        assert 0.0 <= data["aggregate_mean"] <= 1.0, \
            f"Aggregate mean out of range: {data['aggregate_mean']}"


class TestResourceScores:
    @pytest.mark.parametrize("env_name,rid,expected", [
        (env, rid, float(score))
        for env, resources in EXPECTED_SCORES.items()
        for rid, score in resources.items()
    ])
    def test_resource_score(self, env_name, rid, expected):
        data = load_report()
        actual = data["environments"][env_name]["resources"][rid]
        assert actual == pytest.approx(expected, abs=1e-6), \
            f"Score for {env_name}/{rid}: expected {expected:.10f}, got {actual}"


class TestEnvironmentMeans:
    @pytest.mark.parametrize("env_name,expected", [
        (env, float(mean)) for env, mean in EXPECTED_ENV_MEANS.items()
    ])
    def test_env_mean(self, env_name, expected):
        data = load_report()
        actual = data["environments"][env_name]["mean"]
        assert actual == pytest.approx(expected, abs=1e-6), \
            f"Mean for {env_name}: expected {expected:.10f}, got {actual}"

    @pytest.mark.parametrize("env_name", list(EXPECTED_SCORES.keys()))
    def test_env_mean_is_mean_of_resources(self, env_name):
        data = load_report()
        env = data["environments"][env_name]
        computed = sum(env["resources"].values()) / len(env["resources"])
        assert env["mean"] == pytest.approx(computed, abs=1e-9), \
            f"env mean for {env_name} should equal mean of its resource scores"


class TestAggregateMean:
    def test_aggregate_mean(self):
        data = load_report()
        assert data["aggregate_mean"] == pytest.approx(
            float(EXPECTED_AGGREGATE), abs=1e-6
        ), f"Aggregate mean: expected {float(EXPECTED_AGGREGATE):.10f}, got {data['aggregate_mean']}"

    def test_aggregate_is_mean_of_all_resources(self):
        data = load_report()
        all_scores = []
        for env in data["environments"].values():
            all_scores.extend(env["resources"].values())
        computed = sum(all_scores) / len(all_scores)
        assert data["aggregate_mean"] == pytest.approx(computed, abs=1e-9), \
            "aggregate_mean should equal the mean of all resource scores"

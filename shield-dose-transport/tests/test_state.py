
import json
import os
import pytest
import math

TOLERANCE = 0.03  # 3% relative tolerance

REFERENCE_DOSE_RATES = {
    "gcr_1au_avg": {
        "bare": 13.5857,
        "config_A": 12.1738,
        "config_B": 8.4582,
        "config_C": 6.5220,
        "config_D": 6.2560,
        "config_E": 4.2595,
        "config_F": 3.5669,
    },
    "gcr_1au_min": {
        "bare": 19.0200,
        "config_A": 17.0434,
        "config_B": 11.8415,
        "config_C": 9.1308,
        "config_D": 8.7584,
        "config_E": 5.9633,
        "config_F": 4.9937,
    },
    "gcr_1au_max": {
        "bare": 8.1514,
        "config_A": 7.3043,
        "config_B": 5.0749,
        "config_C": 3.9132,
        "config_D": 3.7536,
        "config_E": 2.5557,
        "config_F": 2.1402,
    },
    "gcr_1_5au": {
        "bare": 15.6235,
        "config_A": 13.9999,
        "config_B": 9.7270,
        "config_C": 7.5003,
        "config_D": 7.1944,
        "config_E": 4.8984,
        "config_F": 4.1020,
    },
}

REFERENCE_MISSION_DOSES = {
    "bare": {
        "leg1_dose_mSv": 59.5509,
        "spe_dose_mSv": 0.486928,
        "leg2_dose_mSv": 205.4507,
        "leg3_dose_mSv": 59.5509,
        "total_dose_mSv": 325.0395,
        "within_limit": True,
    },
    "config_A": {
        "leg1_dose_mSv": 53.3623,
        "spe_dose_mSv": 0.410233,
        "leg2_dose_mSv": 184.1000,
        "leg3_dose_mSv": 53.3623,
        "total_dose_mSv": 291.2349,
        "within_limit": True,
    },
    "config_B": {
        "leg1_dose_mSv": 37.0755,
        "spe_dose_mSv": 0.244831,
        "leg2_dose_mSv": 127.9103,
        "leg3_dose_mSv": 37.0755,
        "total_dose_mSv": 202.3061,
        "within_limit": True,
    },
    "config_C": {
        "leg1_dose_mSv": 28.5882,
        "spe_dose_mSv": 0.127191,
        "leg2_dose_mSv": 98.6294,
        "leg3_dose_mSv": 28.5882,
        "total_dose_mSv": 155.9331,
        "within_limit": True,
    },
    "config_D": {
        "leg1_dose_mSv": 27.4222,
        "spe_dose_mSv": 0.132000,
        "leg2_dose_mSv": 94.6067,
        "leg3_dose_mSv": 27.4222,
        "total_dose_mSv": 149.5832,
        "within_limit": True,
    },
    "config_E": {
        "leg1_dose_mSv": 18.6708,
        "spe_dose_mSv": 0.073782,
        "leg2_dose_mSv": 64.4144,
        "leg3_dose_mSv": 18.6708,
        "total_dose_mSv": 101.8299,
        "within_limit": True,
    },
    "config_F": {
        "leg1_dose_mSv": 15.6352,
        "spe_dose_mSv": 0.074426,
        "leg2_dose_mSv": 53.9414,
        "leg3_dose_mSv": 15.6352,
        "total_dose_mSv": 85.2862,
        "within_limit": True,
    },
}


def relative_error(computed, reference):
    if reference == 0:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


class TestConfigDoseRates:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/results/config_dose_rates.json"
        assert os.path.exists(path), f"Output file {path} not found"
        with open(path) as f:
            self.results = json.load(f)

    def test_all_environments_present(self):
        for env in REFERENCE_DOSE_RATES:
            assert env in self.results, f"Missing environment: {env}"

    def test_all_configs_present(self):
        for env in REFERENCE_DOSE_RATES:
            for cfg in REFERENCE_DOSE_RATES[env]:
                assert cfg in self.results[env], (
                    f"Missing config {cfg} in environment {env}"
                )

    @pytest.mark.parametrize(
        "env,cfg",
        [
            (env, cfg)
            for env in REFERENCE_DOSE_RATES
            for cfg in REFERENCE_DOSE_RATES[env]
        ],
    )
    def test_dose_rate_accuracy(self, env, cfg):
        ref = REFERENCE_DOSE_RATES[env][cfg]
        computed = float(self.results[env][cfg])
        err = relative_error(computed, ref)
        assert err <= TOLERANCE, (
            f"{env}/{cfg}: computed={computed:.4f}, "
            f"reference={ref:.4f}, error={err:.4%}"
        )


class TestMissionDoses:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/results/mission_doses.json"
        assert os.path.exists(path), f"Output file {path} not found"
        with open(path) as f:
            self.results = json.load(f)

    def test_all_configs_present(self):
        for cfg in REFERENCE_MISSION_DOSES:
            assert cfg in self.results, f"Missing config: {cfg}"

    @pytest.mark.parametrize("cfg", list(REFERENCE_MISSION_DOSES.keys()))
    def test_leg1_dose(self, cfg):
        ref = REFERENCE_MISSION_DOSES[cfg]["leg1_dose_mSv"]
        computed = float(self.results[cfg]["leg1_dose_mSv"])
        err = relative_error(computed, ref)
        assert err <= TOLERANCE, (
            f"{cfg} leg1: computed={computed:.4f}, "
            f"reference={ref:.4f}, error={err:.4%}"
        )

    @pytest.mark.parametrize("cfg", list(REFERENCE_MISSION_DOSES.keys()))
    def test_spe_dose(self, cfg):
        ref = REFERENCE_MISSION_DOSES[cfg]["spe_dose_mSv"]
        computed = float(self.results[cfg]["spe_dose_mSv"])
        err = relative_error(computed, ref)
        assert err <= TOLERANCE, (
            f"{cfg} SPE: computed={computed:.6f}, "
            f"reference={ref:.6f}, error={err:.4%}"
        )

    @pytest.mark.parametrize("cfg", list(REFERENCE_MISSION_DOSES.keys()))
    def test_leg2_dose(self, cfg):
        ref = REFERENCE_MISSION_DOSES[cfg]["leg2_dose_mSv"]
        computed = float(self.results[cfg]["leg2_dose_mSv"])
        err = relative_error(computed, ref)
        assert err <= TOLERANCE, (
            f"{cfg} leg2: computed={computed:.4f}, "
            f"reference={ref:.4f}, error={err:.4%}"
        )

    @pytest.mark.parametrize("cfg", list(REFERENCE_MISSION_DOSES.keys()))
    def test_leg3_dose(self, cfg):
        ref = REFERENCE_MISSION_DOSES[cfg]["leg3_dose_mSv"]
        computed = float(self.results[cfg]["leg3_dose_mSv"])
        err = relative_error(computed, ref)
        assert err <= TOLERANCE, (
            f"{cfg} leg3: computed={computed:.4f}, "
            f"reference={ref:.4f}, error={err:.4%}"
        )

    @pytest.mark.parametrize("cfg", list(REFERENCE_MISSION_DOSES.keys()))
    def test_total_dose(self, cfg):
        ref = REFERENCE_MISSION_DOSES[cfg]["total_dose_mSv"]
        computed = float(self.results[cfg]["total_dose_mSv"])
        err = relative_error(computed, ref)
        assert err <= TOLERANCE, (
            f"{cfg} total: computed={computed:.4f}, "
            f"reference={ref:.4f}, error={err:.4%}"
        )

    @pytest.mark.parametrize("cfg", list(REFERENCE_MISSION_DOSES.keys()))
    def test_within_limit(self, cfg):
        ref = REFERENCE_MISSION_DOSES[cfg]["within_limit"]
        computed = self.results[cfg]["within_limit"]
        assert computed == ref, (
            f"{cfg} within_limit: computed={computed}, reference={ref}"
        )


import json
import os
import shutil
import sqlite3
import subprocess

import pytest


@pytest.fixture
def results():
    assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"
    with open("/app/results.json") as f:
        data = json.load(f)
    return data


class TestStructure:
    def test_results_has_all_sections(self, results):
        required = [
            "yield_curve_inversions",
            "sahm_rule_episodes",
            "real_ffr",
            "m2_growth",
            "composite_stress",
        ]
        for key in required:
            assert key in results, f"Missing required section: {key}"

    def test_yield_curve_entry_format(self, results):
        inversions = results["yield_curve_inversions"]
        assert isinstance(inversions, list)
        assert len(inversions) > 0
        entry = inversions[0]
        assert "start_date" in entry
        assert "end_date" in entry
        assert "business_days" in entry
        assert "min_spread" in entry

    def test_sahm_entry_format(self, results):
        episodes = results["sahm_rule_episodes"]
        assert isinstance(episodes, list)
        assert len(episodes) > 0
        entry = episodes[0]
        assert "start_date" in entry
        assert "end_date" in entry
        assert "peak_indicator" in entry

    def test_real_ffr_format(self, results):
        real_ffr = results["real_ffr"]
        assert "max" in real_ffr
        assert "min" in real_ffr
        assert "decade_averages" in real_ffr
        assert "date" in real_ffr["max"]
        assert "value" in real_ffr["max"]

    def test_m2_growth_format(self, results):
        m2 = results["m2_growth"]
        assert "regime_counts" in m2
        assert "max_growth" in m2
        assert "min_growth" in m2
        counts = m2["regime_counts"]
        for regime in ["contraction", "low", "moderate", "rapid", "extreme"]:
            assert regime in counts, f"Missing regime: {regime}"

    def test_composite_stress_format(self, results):
        stress = results["composite_stress"]
        assert "stress_months" in stress
        assert "max_stress" in stress
        assert "count" in stress


class TestYieldCurveInversions:
    def test_inversion_count(self, results):
        inversions = results["yield_curve_inversions"]
        assert len(inversions) == 21, (
            f"Expected 21 inversion periods (>=5 biz days), got {len(inversions)}"
        )

    def test_longest_inversion_2022_2024(self, results):
        inversions = results["yield_curve_inversions"]
        longest = max(inversions, key=lambda x: x["business_days"])
        assert longest["business_days"] == 537
        assert longest["start_date"] == "2022-07-06"
        assert longest["end_date"] == "2024-08-26"
        assert abs(longest["min_spread"] - (-1.08)) < 0.01

    def test_volcker_era_inversion(self, results):
        inversions = results["yield_curve_inversions"]
        volcker = [inv for inv in inversions if inv["start_date"].startswith("1978")]
        assert len(volcker) == 1, "Should have exactly one inversion starting in 1978"
        assert volcker[0]["business_days"] == 423
        assert volcker[0]["start_date"] == "1978-08-18"
        assert volcker[0]["end_date"] == "1980-05-01"
        assert abs(volcker[0]["min_spread"] - (-2.41)) < 0.01

    def test_second_volcker_inversion(self, results):
        inversions = results["yield_curve_inversions"]
        v2 = [inv for inv in inversions if inv["start_date"] == "1980-09-12"]
        assert len(v2) == 1
        assert v2[0]["business_days"] == 278
        assert abs(v2[0]["min_spread"] - (-1.70)) < 0.01

    def test_1989_inversion(self, results):
        inversions = results["yield_curve_inversions"]
        inv89 = [inv for inv in inversions if inv["start_date"] == "1989-01-04"]
        assert len(inv89) == 1
        assert inv89[0]["business_days"] == 123

    def test_2000_dotcom_inversion(self, results):
        inversions = results["yield_curve_inversions"]
        dotcom = [inv for inv in inversions if inv["start_date"].startswith("2000-02-1")]
        assert len(dotcom) == 1
        assert dotcom[0]["business_days"] == 220
        assert abs(dotcom[0]["min_spread"] - (-0.52)) < 0.01

    def test_all_min_spreads_negative(self, results):
        inversions = results["yield_curve_inversions"]
        for inv in inversions:
            assert inv["min_spread"] < 0, (
                f"min_spread should be negative, got {inv['min_spread']}"
            )

    def test_all_business_days_at_least_5(self, results):
        inversions = results["yield_curve_inversions"]
        for inv in inversions:
            assert inv["business_days"] >= 5, (
                f"business_days should be >= 5, got {inv['business_days']}"
            )

    def test_inversions_chronological(self, results):
        inversions = results["yield_curve_inversions"]
        starts = [inv["start_date"] for inv in inversions]
        assert starts == sorted(starts), "Inversions should be in chronological order"


class TestSahmRule:
    def test_episode_count(self, results):
        episodes = results["sahm_rule_episodes"]
        assert len(episodes) == 15, f"Expected 15 Sahm episodes, got {len(episodes)}"

    def test_first_episode_1949(self, results):
        episodes = results["sahm_rule_episodes"]
        first = episodes[0]
        assert first["start_date"] == "1949-03"
        assert first["end_date"] == "1950-04"
        assert abs(first["peak_indicator"] - 3.3333) < 0.01

    def test_covid_episode(self, results):
        episodes = results["sahm_rule_episodes"]
        covid = [ep for ep in episodes if ep["start_date"].startswith("2020")]
        assert len(covid) == 1, "Should have exactly one COVID-era Sahm episode"
        assert covid[0]["start_date"] == "2020-04"
        assert covid[0]["end_date"] == "2021-03"
        assert abs(covid[0]["peak_indicator"] - 9.4333) < 0.05

    def test_great_recession_episode(self, results):
        episodes = results["sahm_rule_episodes"]
        gr = [ep for ep in episodes if ep["start_date"] == "2008-02"]
        assert len(gr) == 1
        assert gr[0]["end_date"] == "2010-05"
        assert abs(gr[0]["peak_indicator"] - 3.9667) < 0.05

    def test_2024_episode(self, results):
        episodes = results["sahm_rule_episodes"]
        recent = [ep for ep in episodes if ep["start_date"] == "2024-07"]
        assert len(recent) == 1
        assert recent[0]["end_date"] == "2024-09"
        assert abs(recent[0]["peak_indicator"] - 0.5667) < 0.02

    def test_episode_start_dates_chronological(self, results):
        episodes = results["sahm_rule_episodes"]
        starts = [ep["start_date"] for ep in episodes]
        assert starts == sorted(starts), "Episodes should be in chronological order"

    def test_all_peaks_above_threshold(self, results):
        episodes = results["sahm_rule_episodes"]
        for ep in episodes:
            assert ep["peak_indicator"] >= 0.50, (
                f"Peak should be >= 0.50, got {ep['peak_indicator']}"
            )


class TestRealFFR:
    def test_max_real_ffr(self, results):
        real_ffr = results["real_ffr"]
        assert real_ffr["max"]["date"] == "1981-06"
        assert abs(real_ffr["max"]["value"] - 9.403) < 0.1

    def test_min_real_ffr(self, results):
        real_ffr = results["real_ffr"]
        assert real_ffr["min"]["date"] == "2022-03"
        assert abs(real_ffr["min"]["value"] - (-8.3722)) < 0.1

    def test_1980s_decade_average(self, results):
        decades = results["real_ffr"]["decade_averages"]
        val_1980s = float(decades["1980s"])
        assert abs(val_1980s - 4.4059) < 0.2, (
            f"1980s average should be ~4.41, got {val_1980s}"
        )

    def test_2010s_decade_average_negative(self, results):
        decades = results["real_ffr"]["decade_averages"]
        val_2010s = float(decades["2010s"])
        assert val_2010s < 0, f"2010s average should be negative, got {val_2010s}"
        assert abs(val_2010s - (-1.158)) < 0.2

    def test_1970s_near_zero(self, results):
        decades = results["real_ffr"]["decade_averages"]
        val_1970s = float(decades["1970s"])
        assert abs(val_1970s) < 0.5, (
            f"1970s average should be near zero, got {val_1970s}"
        )

    def test_decade_count(self, results):
        decades = results["real_ffr"]["decade_averages"]
        assert len(decades) == 8, f"Expected 8 decades (1950s-2020s), got {len(decades)}"


class TestM2Growth:
    def test_contraction_count(self, results):
        counts = results["m2_growth"]["regime_counts"]
        assert counts["contraction"] == 15, (
            f"Expected 15 contraction months, got {counts['contraction']}"
        )

    def test_extreme_count(self, results):
        counts = results["m2_growth"]["regime_counts"]
        assert counts["extreme"] == 13, (
            f"Expected 13 extreme months, got {counts['extreme']}"
        )

    def test_total_months(self, results):
        counts = results["m2_growth"]["regime_counts"]
        total = sum(counts.values())
        assert total == 795, f"Total regime months should be 795, got {total}"

    def test_moderate_largest_regime(self, results):
        counts = results["m2_growth"]["regime_counts"]
        assert counts["moderate"] == max(counts.values()), (
            "Moderate should be the most common regime"
        )
        assert counts["moderate"] == 469

    def test_low_count(self, results):
        counts = results["m2_growth"]["regime_counts"]
        assert counts["low"] == 207

    def test_rapid_count(self, results):
        counts = results["m2_growth"]["regime_counts"]
        assert counts["rapid"] == 91

    def test_max_growth(self, results):
        m2 = results["m2_growth"]
        assert m2["max_growth"]["date"] == "2021-02"
        assert abs(m2["max_growth"]["value"] - 26.7753) < 0.1

    def test_min_growth(self, results):
        m2 = results["m2_growth"]
        assert m2["min_growth"]["date"] == "2023-04"
        assert abs(m2["min_growth"]["value"] - (-4.6308)) < 0.1


class TestCompositeStress:
    def test_stress_month_count(self, results):
        stress = results["composite_stress"]
        assert stress["count"] == 79, (
            f"Expected 79 stress months, got {stress['count']}"
        )

    def test_stress_months_list_length(self, results):
        stress = results["composite_stress"]
        assert len(stress["stress_months"]) == stress["count"]

    def test_max_stress_is_covid(self, results):
        stress = results["composite_stress"]
        assert stress["max_stress"]["date"] == "2020-04"
        assert abs(stress["max_stress"]["score"] - 11.1293) < 0.5

    def test_all_stress_scores_above_threshold(self, results):
        stress = results["composite_stress"]
        for entry in stress["stress_months"]:
            assert entry["score"] > 2.0, (
                f"Stress score should be > 2.0, got {entry['score']}"
            )

    def test_volcker_stress_present(self, results):
        stress = results["composite_stress"]
        dates = [m["date"] for m in stress["stress_months"]]
        assert "1981-06" in dates, "1981-06 (Volcker peak) should be a stress month"

    def test_1980_march_stress(self, results):
        stress = results["composite_stress"]
        march_1980 = [
            m for m in stress["stress_months"] if m["date"] == "1980-03"
        ]
        assert len(march_1980) == 1
        assert abs(march_1980[0]["score"] - 3.8229) < 0.3

    def test_stress_months_chronological(self, results):
        stress = results["composite_stress"]
        dates = [m["date"] for m in stress["stress_months"]]
        assert dates == sorted(dates), "Stress months should be chronological"


class TestDatabase:
    @pytest.fixture
    def db(self):
        assert os.path.exists("/app/results.db"), "results.db not found at /app/results.db"
        conn = sqlite3.connect("/app/results.db")
        yield conn
        conn.close()

    def test_all_tables_exist(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor}
        expected = {
            "composite_stress_months",
            "m2_growth_extremes",
            "m2_regime_counts",
            "real_ffr_decades",
            "real_ffr_extremes",
            "sahm_rule_episodes",
            "yield_curve_inversions",
        }
        for t in expected:
            assert t in tables, f"Missing table: {t}"

    def test_yield_curve_inversions_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM yield_curve_inversions").fetchone()[0]
        assert count == 21

    def test_sahm_episodes_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM sahm_rule_episodes").fetchone()[0]
        assert count == 15

    def test_real_ffr_extremes_rows(self, db):
        count = db.execute("SELECT COUNT(*) FROM real_ffr_extremes").fetchone()[0]
        assert count == 2

    def test_real_ffr_decades_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM real_ffr_decades").fetchone()[0]
        assert count == 8

    def test_m2_regimes_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM m2_regime_counts").fetchone()[0]
        assert count == 5

    def test_m2_growth_extremes_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM m2_growth_extremes").fetchone()[0]
        assert count == 2

    def test_composite_stress_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM composite_stress_months").fetchone()[0]
        assert count == 79


class TestBuildReport:
    def test_build_report_executable(self):
        assert os.path.exists("/app/build_report.sh"), "build_report.sh not found"
        assert os.access("/app/build_report.sh", os.X_OK), "build_report.sh not executable"

    def test_build_report_uses_tools(self):
        with open("/app/build_report.sh") as f:
            content = f.read()
        assert "sqlite3" in content, "build_report.sh must use sqlite3"
        assert "jq" in content, "build_report.sh must use jq"

    def test_build_report_regeneration(self):
        shutil.copy2("/app/results.json", "/app/results.json.testbak")
        os.remove("/app/results.json")
        try:
            result = subprocess.run(
                ["/app/build_report.sh"], cwd="/app",
                capture_output=True, timeout=60,
            )
            assert result.returncode == 0, (
                f"build_report.sh failed: {result.stderr.decode()}"
            )
            assert os.path.exists("/app/results.json"), (
                "build_report.sh did not regenerate results.json"
            )
            with open("/app/results.json") as f:
                data = json.load(f)
            assert "yield_curve_inversions" in data
            assert len(data["yield_curve_inversions"]) == 21
        finally:
            if os.path.exists("/app/results.json.testbak"):
                shutil.move("/app/results.json.testbak", "/app/results.json")

    def test_build_report_reads_from_db(self):
        conn = sqlite3.connect("/app/results.db")
        orig = conn.execute(
            "SELECT cnt FROM m2_regime_counts WHERE regime='contraction'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE m2_regime_counts SET cnt = 99999 WHERE regime='contraction'"
        )
        conn.commit()
        try:
            result = subprocess.run(
                ["/app/build_report.sh"], cwd="/app",
                capture_output=True, timeout=60,
            )
            assert result.returncode == 0
            with open("/app/results.json") as f:
                data = json.load(f)
            assert data["m2_growth"]["regime_counts"]["contraction"] == 99999, (
                "build_report.sh must read from results.db, not hardcode values"
            )
        finally:
            conn.execute(
                "UPDATE m2_regime_counts SET cnt = ? WHERE regime='contraction'",
                (orig,),
            )
            conn.commit()
            conn.close()
            subprocess.run(
                ["/app/build_report.sh"], cwd="/app",
                capture_output=True, timeout=60,
            )

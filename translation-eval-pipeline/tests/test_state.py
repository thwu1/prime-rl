"""Tests for the translation benchmark evaluation pipeline.

"""

import json
import os
import pytest

RESULTS_FILE = "/app/results.json"
TOLERANCE = 0.0002


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_FILE), f"Results file not found at {RESULTS_FILE}"
    with open(RESULTS_FILE, "r") as f:
        data = json.load(f)
    return data


def approx(expected, tol=TOLERANCE):
    return pytest.approx(expected, abs=tol)


class TestSchemaConformance:

    def test_schema_validation(self, results):
        """Verify output conforms to the JSON Schema at /app/output_schema.json."""
        import jsonschema
        with open("/app/output_schema.json") as f:
            schema = json.load(f)
        jsonschema.validate(results, schema)


class TestResultsStructure:

    def test_has_projects(self, results):
        assert "projects" in results
        assert isinstance(results["projects"], dict)

    def test_has_language_pairs(self, results):
        assert "language_pairs" in results
        assert isinstance(results["language_pairs"], dict)

    def test_has_overall(self, results):
        assert "overall" in results
        assert isinstance(results["overall"], dict)

    def test_has_directional_analysis(self, results):
        assert "directional_analysis" in results
        assert isinstance(results["directional_analysis"], dict)

    def test_has_framework_analysis(self, results):
        assert "framework_analysis" in results
        assert isinstance(results["framework_analysis"], dict)

    def test_project_count(self, results):
        assert len(results["projects"]) == 10

    def test_language_pair_count(self, results):
        assert len(results["language_pairs"]) == 6


class TestProjectResults:

    def test_proj_01_compile(self, results):
        p = results["projects"]["proj_01"]
        assert p["compile_success"] is True

    def test_proj_01_tests(self, results):
        p = results["projects"]["proj_01"]
        assert p["tests_passed"] == 15
        assert p["tests_total"] == 15
        assert p["pass_rate"] == approx(1.0)
        assert p["all_tests_pass"] is True

    def test_proj_01_langs(self, results):
        p = results["projects"]["proj_01"]
        assert p["source_lang"] == "Python"
        assert p["target_lang"] == "Java"

    def test_proj_02_compile(self, results):
        p = results["projects"]["proj_02"]
        assert p["compile_success"] is True

    def test_proj_02_tests(self, results):
        p = results["projects"]["proj_02"]
        assert p["tests_passed"] == 12
        assert p["tests_total"] == 15
        assert p["pass_rate"] == approx(0.8)
        assert p["all_tests_pass"] is False

    def test_proj_03_compile_failure(self, results):
        p = results["projects"]["proj_03"]
        assert p["compile_success"] is False
        assert p["tests_passed"] == 0
        assert p["tests_total"] == 0
        assert p["pass_rate"] == approx(0.0)
        assert p["all_tests_pass"] is False

    def test_proj_03_langs(self, results):
        p = results["projects"]["proj_03"]
        assert p["source_lang"] == "Python"
        assert p["target_lang"] == "Rust"

    def test_proj_04_tests(self, results):
        p = results["projects"]["proj_04"]
        assert p["compile_success"] is True
        assert p["tests_passed"] == 8
        assert p["tests_total"] == 12
        assert p["pass_rate"] == approx(0.6667)
        assert p["all_tests_pass"] is False

    def test_proj_05_tests(self, results):
        p = results["projects"]["proj_05"]
        assert p["compile_success"] is True
        assert p["tests_passed"] == 20
        assert p["tests_total"] == 20
        assert p["pass_rate"] == approx(1.0)
        assert p["all_tests_pass"] is True

    def test_proj_05_langs(self, results):
        p = results["projects"]["proj_05"]
        assert p["source_lang"] == "Java"
        assert p["target_lang"] == "Python"

    def test_proj_06_tests(self, results):
        p = results["projects"]["proj_06"]
        assert p["compile_success"] is True
        assert p["tests_passed"] == 16
        assert p["tests_total"] == 20
        assert p["pass_rate"] == approx(0.8)
        assert p["all_tests_pass"] is False

    def test_proj_07_tests(self, results):
        p = results["projects"]["proj_07"]
        assert p["compile_success"] is True
        assert p["tests_passed"] == 10
        assert p["tests_total"] == 10
        assert p["pass_rate"] == approx(1.0)
        assert p["all_tests_pass"] is True

    def test_proj_08_tests(self, results):
        p = results["projects"]["proj_08"]
        assert p["compile_success"] is True
        assert p["tests_passed"] == 6
        assert p["tests_total"] == 10
        assert p["pass_rate"] == approx(0.6)
        assert p["all_tests_pass"] is False

    def test_proj_09_tests(self, results):
        p = results["projects"]["proj_09"]
        assert p["compile_success"] is True
        assert p["tests_passed"] == 13
        assert p["tests_total"] == 15
        assert p["pass_rate"] == approx(0.8667)
        assert p["all_tests_pass"] is False

    def test_proj_09_langs(self, results):
        p = results["projects"]["proj_09"]
        assert p["source_lang"] == "Python"
        assert p["target_lang"] == "C++"

    def test_proj_10_tests(self, results):
        p = results["projects"]["proj_10"]
        assert p["compile_success"] is True
        assert p["tests_passed"] == 15
        assert p["tests_total"] == 18
        assert p["pass_rate"] == approx(0.8333)
        assert p["all_tests_pass"] is False

    def test_proj_10_langs(self, results):
        p = results["projects"]["proj_10"]
        assert p["source_lang"] == "C++"
        assert p["target_lang"] == "Python"


class TestLanguagePairAggregates:

    def test_python_to_java(self, results):
        lp = results["language_pairs"]["Python_to_Java"]
        assert lp["num_projects"] == 2
        assert lp["compile_rate"] == approx(1.0)
        assert lp["success_rate"] == approx(0.5)
        assert lp["avg_pass_rate"] == approx(0.9)

    def test_python_to_rust(self, results):
        lp = results["language_pairs"]["Python_to_Rust"]
        assert lp["num_projects"] == 2
        assert lp["compile_rate"] == approx(0.5)
        assert lp["success_rate"] == approx(0.0)
        assert lp["avg_pass_rate"] == approx(0.3333)

    def test_java_to_python(self, results):
        lp = results["language_pairs"]["Java_to_Python"]
        assert lp["num_projects"] == 2
        assert lp["compile_rate"] == approx(1.0)
        assert lp["success_rate"] == approx(0.5)
        assert lp["avg_pass_rate"] == approx(0.9)

    def test_python_to_go(self, results):
        lp = results["language_pairs"]["Python_to_Go"]
        assert lp["num_projects"] == 2
        assert lp["compile_rate"] == approx(1.0)
        assert lp["success_rate"] == approx(0.5)
        assert lp["avg_pass_rate"] == approx(0.8)

    def test_python_to_cpp(self, results):
        lp = results["language_pairs"]["Python_to_C++"]
        assert lp["num_projects"] == 1
        assert lp["compile_rate"] == approx(1.0)
        assert lp["success_rate"] == approx(0.0)
        assert lp["avg_pass_rate"] == approx(0.8667)

    def test_cpp_to_python(self, results):
        lp = results["language_pairs"]["C++_to_Python"]
        assert lp["num_projects"] == 1
        assert lp["compile_rate"] == approx(1.0)
        assert lp["success_rate"] == approx(0.0)
        assert lp["avg_pass_rate"] == approx(0.8333)


class TestOverallStatistics:

    def test_total_projects(self, results):
        assert results["overall"]["total_projects"] == 10

    def test_overall_compile_rate(self, results):
        assert results["overall"]["compile_rate"] == approx(0.9)

    def test_overall_success_rate(self, results):
        assert results["overall"]["success_rate"] == approx(0.3)

    def test_overall_avg_pass_rate(self, results):
        assert results["overall"]["avg_pass_rate"] == approx(0.7567)


class TestDirectionalAnalysis:

    def test_d2s_pairs(self, results):
        d2s = results["directional_analysis"]["dynamic_to_static"]
        assert set(d2s["pairs"]) == {
            "Python_to_Java",
            "Python_to_Rust",
            "Python_to_Go",
            "Python_to_C++",
        }

    def test_d2s_project_count(self, results):
        d2s = results["directional_analysis"]["dynamic_to_static"]
        assert d2s["num_projects"] == 7

    def test_d2s_compile_rate(self, results):
        d2s = results["directional_analysis"]["dynamic_to_static"]
        assert d2s["compile_rate"] == approx(0.8571)

    def test_d2s_success_rate(self, results):
        d2s = results["directional_analysis"]["dynamic_to_static"]
        assert d2s["success_rate"] == approx(0.2857)

    def test_d2s_avg_pass_rate(self, results):
        d2s = results["directional_analysis"]["dynamic_to_static"]
        assert d2s["avg_pass_rate"] == approx(0.7048)

    def test_s2d_pairs(self, results):
        s2d = results["directional_analysis"]["static_to_dynamic"]
        assert set(s2d["pairs"]) == {"Java_to_Python", "C++_to_Python"}

    def test_s2d_project_count(self, results):
        s2d = results["directional_analysis"]["static_to_dynamic"]
        assert s2d["num_projects"] == 3

    def test_s2d_compile_rate(self, results):
        s2d = results["directional_analysis"]["static_to_dynamic"]
        assert s2d["compile_rate"] == approx(1.0)

    def test_s2d_success_rate(self, results):
        s2d = results["directional_analysis"]["static_to_dynamic"]
        assert s2d["success_rate"] == approx(0.3333)

    def test_s2d_avg_pass_rate(self, results):
        s2d = results["directional_analysis"]["static_to_dynamic"]
        assert s2d["avg_pass_rate"] == approx(0.8778)


class TestFrameworkAnalysis:

    def test_has_all_frameworks(self, results):
        fa = results["framework_analysis"]
        expected = {"junit", "cargo_test", "pytest", "go_test", "gtest"}
        assert set(fa.keys()) == expected

    def test_framework_schema_fields(self, results):
        """Every framework entry has all required fields."""
        required = {
            "projects_using", "projects_compiled",
            "total_tests_executed", "total_tests_passed",
            "aggregate_pass_rate",
        }
        for fw, metrics in results["framework_analysis"].items():
            assert required.issubset(set(metrics.keys())), \
                f"Missing fields in {fw}: {required - set(metrics.keys())}"

    def test_junit_metrics(self, results):
        m = results["framework_analysis"]["junit"]
        assert m["projects_using"] == 2
        assert m["projects_compiled"] == 2
        assert m["total_tests_executed"] == 30
        assert m["total_tests_passed"] == 27
        assert m["aggregate_pass_rate"] == approx(0.9)

    def test_cargo_test_metrics(self, results):
        m = results["framework_analysis"]["cargo_test"]
        assert m["projects_using"] == 2
        assert m["projects_compiled"] == 1
        assert m["total_tests_executed"] == 12
        assert m["total_tests_passed"] == 8
        assert m["aggregate_pass_rate"] == approx(0.6667)

    def test_pytest_metrics(self, results):
        m = results["framework_analysis"]["pytest"]
        assert m["projects_using"] == 3
        assert m["projects_compiled"] == 3
        assert m["total_tests_executed"] == 58
        assert m["total_tests_passed"] == 51
        assert m["aggregate_pass_rate"] == approx(0.8793)

    def test_go_test_metrics(self, results):
        m = results["framework_analysis"]["go_test"]
        assert m["projects_using"] == 2
        assert m["projects_compiled"] == 2
        assert m["total_tests_executed"] == 20
        assert m["total_tests_passed"] == 16
        assert m["aggregate_pass_rate"] == approx(0.8)

    def test_gtest_metrics(self, results):
        m = results["framework_analysis"]["gtest"]
        assert m["projects_using"] == 1
        assert m["projects_compiled"] == 1
        assert m["total_tests_executed"] == 15
        assert m["total_tests_passed"] == 13
        assert m["aggregate_pass_rate"] == approx(0.8667)

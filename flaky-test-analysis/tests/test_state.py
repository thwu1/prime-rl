"""
Tests for the flaky test cross-dataset analysis pipeline.

"""

import json
import csv
import os
import statistics
from collections import Counter
from pathlib import Path

import pytest

REPORT_PATH = "/app/analysis_report.json"
DATA_DIR = "/app/data"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def pr_data():
    with open(os.path.join(DATA_DIR, "pr-data.csv"), newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def gr_data():
    with open(os.path.join(DATA_DIR, "gr-data.csv"), newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def py_data():
    with open(os.path.join(DATA_DIR, "py-data.csv"), newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def odr_data():
    with open(os.path.join(DATA_DIR, "odr-tests.csv"), newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def tic_fic_data():
    with open(os.path.join(DATA_DIR, "tic-fic-data.csv"), newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def tso_iso_data():
    with open(os.path.join(DATA_DIR, "tso-iso-rates.csv"), newline="") as f:
        return list(csv.DictReader(f))


# ============================================================
# 1. Report structure and top-level keys
# ============================================================


class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH)

    def test_report_is_valid_json(self):
        with open(REPORT_PATH) as f:
            json.load(f)

    def test_required_top_level_keys(self, report):
        required = [
            "dataset_summary",
            "category_fix_rates",
            "order_dependency_graph",
            "tic_fic_analysis",
            "tso_iso_analysis",
            "cross_dataset_analysis",
        ]
        for key in required:
            assert key in report, f"Missing top-level key: {key}"


# ============================================================
# 2. Dataset summary
# ============================================================


class TestDatasetSummary:
    def test_pr_data_rows(self, report, pr_data):
        expected = len(pr_data)
        assert report["dataset_summary"]["pr_data_rows"] == expected

    def test_gr_data_rows(self, report, gr_data):
        expected = len(gr_data)
        assert report["dataset_summary"]["gr_data_rows"] == expected

    def test_py_data_rows(self, report, py_data):
        expected = len(py_data)
        assert report["dataset_summary"]["py_data_rows"] == expected

    def test_pr_unique_projects(self, report, pr_data):
        expected = len(set(r["Project URL"] for r in pr_data))
        assert report["dataset_summary"]["pr_unique_projects"] == expected

    def test_gr_unique_projects(self, report, gr_data):
        expected = len(set(r["Project URL"] for r in gr_data))
        assert report["dataset_summary"]["gr_unique_projects"] == expected

    def test_py_unique_projects(self, report, py_data):
        expected = len(set(r["Project URL"] for r in py_data))
        assert report["dataset_summary"]["py_unique_projects"] == expected


# ============================================================
# 3. Category fix rates (pr-data.csv only)
# ============================================================


class TestCategoryFixRates:
    @pytest.fixture(scope="class")
    def expected_rates(self, pr_data):
        cat_stats = {}
        for r in pr_data:
            raw_cat = r.get("Category") or ""
            if not raw_cat.strip():
                continue
            cats = [c.strip() for c in raw_cat.split(";")]
            status = r.get("Status") or ""
            for cat in cats:
                if not cat:
                    continue
                if cat not in cat_stats:
                    cat_stats[cat] = {"total": 0, "accepted": 0, "with_status": 0}
                cat_stats[cat]["total"] += 1
                if status != "":
                    cat_stats[cat]["with_status"] += 1
                if status == "Accepted":
                    cat_stats[cat]["accepted"] += 1
        for cat in cat_stats:
            ws = cat_stats[cat]["with_status"]
            cat_stats[cat]["fix_rate"] = (
                cat_stats[cat]["accepted"] / ws if ws > 0 else 0.0
            )
        return cat_stats

    def test_all_categories_present(self, report, expected_rates):
        for cat in expected_rates:
            assert cat in report["category_fix_rates"], f"Missing category: {cat}"

    def test_id_total(self, report, expected_rates):
        assert report["category_fix_rates"]["ID"]["total"] == expected_rates["ID"]["total"]

    def test_od_total(self, report, expected_rates):
        assert report["category_fix_rates"]["OD"]["total"] == expected_rates["OD"]["total"]

    def test_nio_total(self, report, expected_rates):
        assert report["category_fix_rates"]["NIO"]["total"] == expected_rates["NIO"]["total"]

    def test_id_accepted(self, report, expected_rates):
        assert report["category_fix_rates"]["ID"]["accepted"] == expected_rates["ID"]["accepted"]

    def test_id_with_status(self, report, expected_rates):
        assert report["category_fix_rates"]["ID"]["with_status"] == expected_rates["ID"]["with_status"]

    def test_id_fix_rate(self, report, expected_rates):
        assert abs(report["category_fix_rates"]["ID"]["fix_rate"] - expected_rates["ID"]["fix_rate"]) < 0.01

    def test_od_vic_fix_rate(self, report, expected_rates):
        assert abs(report["category_fix_rates"]["OD-Vic"]["fix_rate"] - expected_rates["OD-Vic"]["fix_rate"]) < 0.01

    def test_nio_fix_rate(self, report, expected_rates):
        assert abs(report["category_fix_rates"]["NIO"]["fix_rate"] - expected_rates["NIO"]["fix_rate"]) < 0.01

    def test_nod_fix_rate(self, report, expected_rates):
        assert abs(report["category_fix_rates"]["NOD"]["fix_rate"] - expected_rates["NOD"]["fix_rate"]) < 0.01

    def test_fix_rate_is_float(self, report):
        for cat, vals in report["category_fix_rates"].items():
            assert isinstance(vals["fix_rate"], (int, float)), f"fix_rate for {cat} is not numeric"


# ============================================================
# 4. Order dependency graph analysis
# ============================================================


class TestOrderDependencyGraph:
    @pytest.fixture(scope="class")
    def expected_graph(self, odr_data):
        result = {}
        result["total_relationships"] = len(odr_data)
        result["unique_od_tests"] = len(set(r["OD-test"] for r in odr_data))
        result["unique_projects"] = len(set(r["Project URL"] for r in odr_data))
        result["victim_count"] = sum(1 for r in odr_data if r["OD-test-type"] == "victim")
        result["brittle_count"] = sum(1 for r in odr_data if r["OD-test-type"] == "brittle")

        # Build undirected graph
        edges = set()
        all_nodes = set()
        for r in odr_data:
            od = r["OD-test"]
            vp = r["Relevant-test(if it is VP/BSS)"]
            vpc = r.get("Relevant-test(if it is VPC)", "")
            tests_in_row = [t for t in [od, vp, vpc] if t]
            for t in tests_in_row:
                all_nodes.add(t)
            for i in range(len(tests_in_row)):
                for j in range(i + 1, len(tests_in_row)):
                    a, b = tests_in_row[i], tests_in_row[j]
                    edges.add((min(a, b), max(a, b)))

        result["num_nodes"] = len(all_nodes)
        result["num_edges"] = len(edges)

        # Connected components via union-find
        parent = {n: n for n in all_nodes}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            a, b = find(a), find(b)
            if a != b:
                parent[a] = b

        for a, b in edges:
            union(a, b)

        comp_sizes = Counter(find(n) for n in all_nodes)
        result["connected_components"] = len(comp_sizes)
        result["largest_component_size"] = max(comp_sizes.values())
        return result

    def test_total_relationships(self, report, expected_graph):
        assert report["order_dependency_graph"]["total_relationships"] == expected_graph["total_relationships"]

    def test_unique_od_tests(self, report, expected_graph):
        assert report["order_dependency_graph"]["unique_od_tests"] == expected_graph["unique_od_tests"]

    def test_unique_projects(self, report, expected_graph):
        assert report["order_dependency_graph"]["unique_projects"] == expected_graph["unique_projects"]

    def test_victim_count(self, report, expected_graph):
        assert report["order_dependency_graph"]["victim_count"] == expected_graph["victim_count"]

    def test_brittle_count(self, report, expected_graph):
        assert report["order_dependency_graph"]["brittle_count"] == expected_graph["brittle_count"]

    def test_num_nodes(self, report, expected_graph):
        assert report["order_dependency_graph"]["num_nodes"] == expected_graph["num_nodes"]

    def test_num_edges(self, report, expected_graph):
        assert report["order_dependency_graph"]["num_edges"] == expected_graph["num_edges"]

    def test_connected_components(self, report, expected_graph):
        assert report["order_dependency_graph"]["connected_components"] == expected_graph["connected_components"]

    def test_largest_component_size(self, report, expected_graph):
        assert report["order_dependency_graph"]["largest_component_size"] == expected_graph["largest_component_size"]


# ============================================================
# 5. TIC-FIC analysis
# ============================================================


class TestTicFicAnalysis:
    @pytest.fixture(scope="class")
    def expected_tic_fic(self, tic_fic_data):
        result = {}
        result["total_tests"] = len(tic_fic_data)
        result["tic_equals_fic_true"] = sum(
            1 for r in tic_fic_data if r["TIC = FIC"] == "TRUE"
        )
        result["tic_equals_fic_false"] = sum(
            1 for r in tic_fic_data if r["TIC = FIC"] == "FALSE"
        )
        days = [
            float(r["Days Between TIC-FIC"])
            for r in tic_fic_data
            if r["TIC = FIC"] == "FALSE" and r["Days Between TIC-FIC"]
        ]
        result["mean_days_between"] = statistics.mean(days) if days else 0.0
        result["median_days_between"] = statistics.median(days) if days else 0.0
        result["max_days_between"] = max(days) if days else 0.0
        return result

    def test_total_tests(self, report, expected_tic_fic):
        assert report["tic_fic_analysis"]["total_tests"] == expected_tic_fic["total_tests"]

    def test_tic_equals_fic_true(self, report, expected_tic_fic):
        assert report["tic_fic_analysis"]["tic_equals_fic_true"] == expected_tic_fic["tic_equals_fic_true"]

    def test_tic_equals_fic_false(self, report, expected_tic_fic):
        assert report["tic_fic_analysis"]["tic_equals_fic_false"] == expected_tic_fic["tic_equals_fic_false"]

    def test_mean_days_between(self, report, expected_tic_fic):
        assert abs(
            report["tic_fic_analysis"]["mean_days_between"]
            - expected_tic_fic["mean_days_between"]
        ) < 1.0

    def test_median_days_between(self, report, expected_tic_fic):
        assert abs(
            report["tic_fic_analysis"]["median_days_between"]
            - expected_tic_fic["median_days_between"]
        ) < 1.0

    def test_max_days_between(self, report, expected_tic_fic):
        assert abs(
            report["tic_fic_analysis"]["max_days_between"]
            - expected_tic_fic["max_days_between"]
        ) < 1.0


# ============================================================
# 6. TSO-ISO analysis
# ============================================================


class TestTsoIsoAnalysis:
    @pytest.fixture(scope="class")
    def expected_tso(self, tso_iso_data):
        result = {}
        result["total_tests"] = len(tso_iso_data)
        sig = 0
        nonsig = 0
        suite_worse = 0
        suite_rates = []
        iso_rates = []
        for r in tso_iso_data:
            pval = float(r["P-Value"])
            total_suite = float(r["Total Runs In Test Suite"])
            passed_suite = float(r["Number of Times Test Passed In Test Suite"])
            total_iso = float(r["Total Runs In Isolation"])
            passed_iso = float(r["Number of Times Test Passed In Isolation"])
            sr = passed_suite / total_suite if total_suite > 0 else 0
            ir = passed_iso / total_iso if total_iso > 0 else 0
            suite_rates.append(sr)
            iso_rates.append(ir)
            if pval < 0.05:
                sig += 1
                if sr < ir:
                    suite_worse += 1
            else:
                nonsig += 1
        result["significant_count"] = sig
        result["nonsignificant_count"] = nonsig
        result["mean_suite_pass_rate"] = statistics.mean(suite_rates)
        result["mean_isolation_pass_rate"] = statistics.mean(iso_rates)
        result["suite_worse_count"] = suite_worse
        return result

    def test_total_tests(self, report, expected_tso):
        assert report["tso_iso_analysis"]["total_tests"] == expected_tso["total_tests"]

    def test_significant_count(self, report, expected_tso):
        assert report["tso_iso_analysis"]["significant_count"] == expected_tso["significant_count"]

    def test_nonsignificant_count(self, report, expected_tso):
        assert report["tso_iso_analysis"]["nonsignificant_count"] == expected_tso["nonsignificant_count"]

    def test_mean_suite_pass_rate(self, report, expected_tso):
        assert abs(
            report["tso_iso_analysis"]["mean_suite_pass_rate"]
            - expected_tso["mean_suite_pass_rate"]
        ) < 0.01

    def test_mean_isolation_pass_rate(self, report, expected_tso):
        assert abs(
            report["tso_iso_analysis"]["mean_isolation_pass_rate"]
            - expected_tso["mean_isolation_pass_rate"]
        ) < 0.01

    def test_suite_worse_count(self, report, expected_tso):
        assert report["tso_iso_analysis"]["suite_worse_count"] == expected_tso["suite_worse_count"]


# ============================================================
# 7. Cross-dataset analysis
# ============================================================


class TestCrossDatasetAnalysis:
    @pytest.fixture(scope="class")
    def expected_cross(self, pr_data, odr_data, tso_iso_data):
        pr_projects = set(r["Project URL"] for r in pr_data)
        odr_projects = set(r["Project URL"] for r in odr_data)
        tso_projects = set(r["Project URL"] for r in tso_iso_data)
        common = sorted(pr_projects & odr_projects & tso_projects)

        # Build pr-data lookup: (Project URL, test name) -> status
        pr_lookup = {}
        for r in pr_data:
            key = (
                r["Project URL"],
                r["Fully-Qualified Test Name (packageName.ClassName.methodName)"],
            )
            pr_lookup[key] = r["Status"]

        # Unique OD-tests found in pr-data
        found_keys = set()
        accepted_keys = set()
        for r in odr_data:
            key = (r["Project URL"], r["OD-test"])
            if key in pr_lookup:
                found_keys.add(key)
                if pr_lookup[key] == "Accepted":
                    accepted_keys.add(key)

        return {
            "projects_in_all_java_datasets": common,
            "unique_odr_tests_in_pr_data": len(found_keys),
            "unique_odr_tests_accepted": len(accepted_keys),
        }

    def test_projects_in_all_java_datasets(self, report, expected_cross):
        actual = sorted(report["cross_dataset_analysis"]["projects_in_all_java_datasets"])
        assert actual == expected_cross["projects_in_all_java_datasets"]

    def test_projects_count(self, report, expected_cross):
        assert len(report["cross_dataset_analysis"]["projects_in_all_java_datasets"]) == len(
            expected_cross["projects_in_all_java_datasets"]
        )

    def test_unique_odr_tests_in_pr_data(self, report, expected_cross):
        assert (
            report["cross_dataset_analysis"]["unique_odr_tests_in_pr_data"]
            == expected_cross["unique_odr_tests_in_pr_data"]
        )

    def test_unique_odr_tests_accepted(self, report, expected_cross):
        assert (
            report["cross_dataset_analysis"]["unique_odr_tests_accepted"]
            == expected_cross["unique_odr_tests_accepted"]
        )


# ============================================================
# 8. Data type validation
# ============================================================


class TestDataTypes:
    def test_dataset_summary_integers(self, report):
        for key in ["pr_data_rows", "gr_data_rows", "py_data_rows",
                     "pr_unique_projects", "gr_unique_projects", "py_unique_projects"]:
            assert isinstance(report["dataset_summary"][key], int), f"{key} should be int"

    def test_graph_integers(self, report):
        for key in ["total_relationships", "unique_od_tests", "unique_projects",
                     "victim_count", "brittle_count", "num_nodes", "num_edges",
                     "connected_components", "largest_component_size"]:
            assert isinstance(report["order_dependency_graph"][key], int), f"{key} should be int"

    def test_tic_fic_floats(self, report):
        for key in ["mean_days_between", "median_days_between", "max_days_between"]:
            assert isinstance(report["tic_fic_analysis"][key], (int, float)), f"{key} should be numeric"

    def test_tso_iso_floats(self, report):
        for key in ["mean_suite_pass_rate", "mean_isolation_pass_rate"]:
            assert isinstance(report["tso_iso_analysis"][key], (int, float)), f"{key} should be numeric"

    def test_cross_dataset_list(self, report):
        assert isinstance(
            report["cross_dataset_analysis"]["projects_in_all_java_datasets"], list
        )

    def test_analyzer_script_exists(self):
        assert os.path.exists("/app/flaky_analyzer.py"), "Analyzer script not found"

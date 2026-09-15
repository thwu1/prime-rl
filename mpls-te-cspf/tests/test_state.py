
import json
import os
import pytest


@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


def get_lsp(results, name):
    for r in results["lsp_results"]:
        if r["name"] == name:
            return r
    pytest.fail(f"LSP '{name}' not found in results")


def get_billing(results, name):
    for b in results["billing_summary"]:
        if b["lsp_name"] == name:
            return b
    pytest.fail(f"Billing entry for '{name}' not found")


def get_risk(results, name):
    for r in results["risk_assessment"]:
        if r["lsp_name"] == name:
            return r
    pytest.fail(f"Risk entry for '{name}' not found")


# ---------- structural checks ----------

class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_has_lsp_results(self, results):
        assert "lsp_results" in results
        assert len(results["lsp_results"]) == 7

    def test_has_link_utilization(self, results):
        assert "link_utilization" in results
        assert len(results["link_utilization"]) == 7

    def test_results_order(self, results):
        names = [r["name"] for r in results["lsp_results"]]
        assert names == [
            "lsp-gold", "lsp-silver", "lsp-diverse-1", "lsp-diverse-2",
            "lsp-best-effort", "lsp-premium", "lsp-constrained"
        ]

    def test_has_billing_summary(self, results):
        assert "billing_summary" in results
        assert len(results["billing_summary"]) == 7

    def test_has_risk_assessment(self, results):
        assert "risk_assessment" in results
        assert len(results["risk_assessment"]) == 7

    def test_billing_order(self, results):
        names = [b["lsp_name"] for b in results["billing_summary"]]
        assert names == [
            "lsp-gold", "lsp-silver", "lsp-diverse-1", "lsp-diverse-2",
            "lsp-best-effort", "lsp-premium", "lsp-constrained"
        ]

    def test_risk_order(self, results):
        names = [r["lsp_name"] for r in results["risk_assessment"]]
        assert names == [
            "lsp-gold", "lsp-silver", "lsp-diverse-1", "lsp-diverse-2",
            "lsp-best-effort", "lsp-premium", "lsp-constrained"
        ]


# ---------- LSP: lsp-gold ----------

class TestLspGold:
    def test_status(self, results):
        assert get_lsp(results, "lsp-gold")["status"] == "established"

    def test_path(self, results):
        assert get_lsp(results, "lsp-gold")["path"] == ["A", "B", "E"]

    def test_cost(self, results):
        assert get_lsp(results, "lsp-gold")["cost"] == 25


# ---------- LSP: lsp-silver ----------

class TestLspSilver:
    def test_status(self, results):
        assert get_lsp(results, "lsp-silver")["status"] == "established"

    def test_path(self, results):
        assert get_lsp(results, "lsp-silver")["path"] == ["A", "C", "D", "E"]

    def test_cost(self, results):
        assert get_lsp(results, "lsp-silver")["cost"] == 35


# ---------- LSP: lsp-diverse-1 ----------

class TestLspDiverse1:
    def test_status(self, results):
        assert get_lsp(results, "lsp-diverse-1")["status"] == "established"

    def test_path(self, results):
        assert get_lsp(results, "lsp-diverse-1")["path"] == ["A", "C", "E"]

    def test_cost(self, results):
        assert get_lsp(results, "lsp-diverse-1")["cost"] == 40


# ---------- LSP: lsp-diverse-2 ----------

class TestLspDiverse2:
    def test_status(self, results):
        assert get_lsp(results, "lsp-diverse-2")["status"] == "established"

    def test_path(self, results):
        assert get_lsp(results, "lsp-diverse-2")["path"] == ["A", "B", "E"]

    def test_cost(self, results):
        assert get_lsp(results, "lsp-diverse-2")["cost"] == 25


# ---------- LSP: lsp-best-effort ----------

class TestLspBestEffort:
    def test_status(self, results):
        assert get_lsp(results, "lsp-best-effort")["status"] == "preempted"

    def test_path_empty(self, results):
        assert get_lsp(results, "lsp-best-effort")["path"] == []

    def test_cost_zero(self, results):
        assert get_lsp(results, "lsp-best-effort")["cost"] == 0

    def test_preempted_by(self, results):
        assert get_lsp(results, "lsp-best-effort")["preempted_by"] == "lsp-premium"


# ---------- LSP: lsp-premium ----------

class TestLspPremium:
    def test_status(self, results):
        assert get_lsp(results, "lsp-premium")["status"] == "established"

    def test_path(self, results):
        assert get_lsp(results, "lsp-premium")["path"] == ["A", "B", "D", "E"]

    def test_cost(self, results):
        assert get_lsp(results, "lsp-premium")["cost"] == 30


# ---------- LSP: lsp-constrained ----------

class TestLspConstrained:
    def test_status(self, results):
        assert get_lsp(results, "lsp-constrained")["status"] == "established"

    def test_path(self, results):
        assert get_lsp(results, "lsp-constrained")["path"] == ["B", "D"]

    def test_cost(self, results):
        assert get_lsp(results, "lsp-constrained")["cost"] == 10


# ---------- Link utilization ----------

class TestLinkUtilization:
    def test_link_ab(self, results):
        u = results["link_utilization"]["A-B"]
        assert u["capacity"] == 15
        assert u["reserved"] == 15
        assert u["available"] == 0

    def test_link_ac(self, results):
        u = results["link_utilization"]["A-C"]
        assert u["capacity"] == 15
        assert u["reserved"] == 12
        assert u["available"] == 3

    def test_link_bd(self, results):
        u = results["link_utilization"]["B-D"]
        assert u["capacity"] == 10
        assert u["reserved"] == 7
        assert u["available"] == 3

    def test_link_be(self, results):
        u = results["link_utilization"]["B-E"]
        assert u["capacity"] == 10
        assert u["reserved"] == 10
        assert u["available"] == 0

    def test_link_cd(self, results):
        u = results["link_utilization"]["C-D"]
        assert u["capacity"] == 10
        assert u["reserved"] == 7
        assert u["available"] == 3

    def test_link_de(self, results):
        u = results["link_utilization"]["D-E"]
        assert u["capacity"] == 15
        assert u["reserved"] == 12
        assert u["available"] == 3

    def test_link_ce(self, results):
        u = results["link_utilization"]["C-E"]
        assert u["capacity"] == 5
        assert u["reserved"] == 5
        assert u["available"] == 0

    def test_utilization_consistency(self, results):
        """reserved + available must equal capacity for every link"""
        for link_name, u in results["link_utilization"].items():
            assert u["reserved"] + u["available"] == u["capacity"], (
                f"Link {link_name}: {u['reserved']} + {u['available']} != {u['capacity']}"
            )


# ---------- Billing summary (NMS integration) ----------

class TestBillingSummary:
    def test_gold_billing(self, results):
        b = get_billing(results, "lsp-gold")
        assert b["customer"] == "ACME Corp"
        assert b["sla_tier"] == "platinum"
        assert b["bandwidth_gbps"] == 7
        # path A-B-E: 7 * (1200 + 1100) = 16100
        assert b["monthly_cost_usd"] == 16100

    def test_silver_billing(self, results):
        b = get_billing(results, "lsp-silver")
        assert b["customer"] == "Beta Inc"
        assert b["sla_tier"] == "gold"
        assert b["bandwidth_gbps"] == 7
        # path A-C-D-E: 7 * (800 + 900 + 1000) = 18900
        assert b["monthly_cost_usd"] == 18900

    def test_diverse1_billing(self, results):
        b = get_billing(results, "lsp-diverse-1")
        assert b["customer"] == "ACME Corp"
        assert b["sla_tier"] == "gold"
        assert b["bandwidth_gbps"] == 5
        # path A-C-E: 5 * (800 + 2000) = 14000
        assert b["monthly_cost_usd"] == 14000

    def test_diverse2_billing(self, results):
        b = get_billing(results, "lsp-diverse-2")
        assert b["customer"] == "ACME Corp"
        assert b["sla_tier"] == "silver"
        assert b["bandwidth_gbps"] == 3
        # path A-B-E: 3 * (1200 + 1100) = 6900
        assert b["monthly_cost_usd"] == 6900

    def test_best_effort_billing(self, results):
        b = get_billing(results, "lsp-best-effort")
        assert b["customer"] == "Gamma LLC"
        assert b["sla_tier"] == "bronze"
        assert b["bandwidth_gbps"] == 0
        assert b["monthly_cost_usd"] == 0

    def test_premium_billing(self, results):
        b = get_billing(results, "lsp-premium")
        assert b["customer"] == "Delta Corp"
        assert b["sla_tier"] == "platinum"
        assert b["bandwidth_gbps"] == 5
        # path A-B-D-E: 5 * (1200 + 1500 + 1000) = 18500
        assert b["monthly_cost_usd"] == 18500

    def test_constrained_billing(self, results):
        b = get_billing(results, "lsp-constrained")
        assert b["customer"] == "Beta Inc"
        assert b["sla_tier"] == "silver"
        assert b["bandwidth_gbps"] == 2
        # path B-D: 2 * 1500 = 3000
        assert b["monthly_cost_usd"] == 3000


# ---------- Risk assessment (NMS integration) ----------

class TestRiskAssessment:
    def test_gold_risk(self, results):
        r = get_risk(results, "lsp-gold")
        # path A-B(srlg1), B-E(srlg1) => srlgs [1]
        assert r["path_srlgs"] == [1]
        assert r["max_risk_score"] == pytest.approx(0.85)

    def test_silver_risk(self, results):
        r = get_risk(results, "lsp-silver")
        # path A-C(srlg2), C-D(srlg3), D-E(srlg4) => srlgs [2,3,4]
        assert r["path_srlgs"] == [2, 3, 4]
        assert r["max_risk_score"] == pytest.approx(0.65)

    def test_diverse1_risk(self, results):
        r = get_risk(results, "lsp-diverse-1")
        # path A-C(srlg2), C-E(srlg5) => srlgs [2,5]
        assert r["path_srlgs"] == [2, 5]
        assert r["max_risk_score"] == pytest.approx(0.90)

    def test_diverse2_risk(self, results):
        r = get_risk(results, "lsp-diverse-2")
        # path A-B(srlg1), B-E(srlg1) => srlgs [1]
        assert r["path_srlgs"] == [1]
        assert r["max_risk_score"] == pytest.approx(0.85)

    def test_best_effort_risk(self, results):
        r = get_risk(results, "lsp-best-effort")
        assert r["path_srlgs"] == []
        assert r["max_risk_score"] == pytest.approx(0.0)

    def test_premium_risk(self, results):
        r = get_risk(results, "lsp-premium")
        # path A-B(srlg1), B-D(srlg3), D-E(srlg4) => srlgs [1,3,4]
        assert r["path_srlgs"] == [1, 3, 4]
        assert r["max_risk_score"] == pytest.approx(0.85)

    def test_constrained_risk(self, results):
        r = get_risk(results, "lsp-constrained")
        # path B-D(srlg3) => srlgs [3]
        assert r["path_srlgs"] == [3]
        assert r["max_risk_score"] == pytest.approx(0.65)


# ---------- Topology SVG (Graphviz output) ----------

class TestTopologySvg:
    def test_svg_exists(self):
        assert os.path.exists("/app/topology.svg"), "topology.svg not found"

    def test_svg_is_valid(self):
        with open("/app/topology.svg") as f:
            content = f.read()
        assert len(content) > 100, "SVG file too small to be valid"
        assert "<svg" in content, "File does not contain SVG markup"

    def test_svg_contains_routers(self):
        with open("/app/topology.svg") as f:
            content = f.read()
        for router in ["A", "B", "C", "D", "E"]:
            assert f"<title>{router}</title>" in content, (
                f"Router node '{router}' not found in SVG topology diagram"
            )

    def test_dot_source_exists(self):
        assert os.path.exists("/app/topology.dot"), "topology.dot source not found"

    def test_dot_source_valid(self):
        with open("/app/topology.dot") as f:
            content = f.read()
        assert "digraph" in content or "graph" in content, (
            "DOT source does not contain valid graph declaration"
        )

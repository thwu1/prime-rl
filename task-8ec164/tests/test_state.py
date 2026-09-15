
import json
import math
import os
import re
import sqlite3
import subprocess
import pytest

REPORT_PATH = "/app/analysis_report.json"
DB_PATH = "/app/selene_model.db"
DOT_PATH = "/app/traceability.dot"
G0 = 9.80665


@pytest.fixture(scope="session")
def report():
    assert os.path.isfile(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def db():
    assert os.path.isfile(DB_PATH), f"Database not found at {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def dot_content():
    assert os.path.isfile(DOT_PATH), f"DOT file not found at {DOT_PATH}"
    with open(DOT_PATH) as f:
        return f.read()


def nav(d, *keys):
    """Navigate nested dict by key path."""
    for k in keys:
        d = d[k]
    return d


# ===== Structure Tests =====

class TestStructure:
    def test_report_exists(self, report):
        assert report is not None

    def test_top_level_keys(self, report):
        expected = {"mass_rollup", "delta_v_budget", "power_budget",
                    "requirements_verification", "traceability",
                    "derivation_chains"}
        assert expected.issubset(set(report.keys()))

    def test_mass_rollup_has_root(self, report):
        assert "seleneSystem" in report["mass_rollup"]

    def test_delta_v_has_stages(self, report):
        dv = report["delta_v_budget"]
        assert "transferVehicle" in dv
        assert "lander" in dv
        assert "totalDeltaV" in dv


# ===== Mass Rollup Tests =====

class TestMassRollup:
    def test_system_total_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem", "mass")
        assert mass == pytest.approx(17068.0, abs=0.5)

    def test_transfer_vehicle_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "transferVehicle", "mass")
        assert mass == pytest.approx(6008.0, abs=0.5)

    def test_lander_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "lander", "mass")
        assert mass == pytest.approx(11060.0, abs=0.5)

    def test_tv_propulsion_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "transferVehicle",
                   "children", "tvPropulsion", "mass")
        assert mass == pytest.approx(5570.0, abs=0.5)

    def test_ln_propulsion_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "lander",
                   "children", "lnPropulsion", "mass")
        assert mass == pytest.approx(8070.0, abs=0.5)

    def test_tv_power_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "transferVehicle",
                   "children", "tvPower", "mass")
        assert mass == pytest.approx(66.0, abs=0.5)

    def test_ln_power_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "lander",
                   "children", "lnPower", "mass")
        assert mass == pytest.approx(100.0, abs=0.5)

    def test_tv_structure_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "transferVehicle",
                   "children", "tvStructure", "mass")
        assert mass == pytest.approx(320.0, abs=0.5)

    def test_ln_payload_mass(self, report):
        mass = nav(report, "mass_rollup", "seleneSystem",
                   "children", "lander",
                   "children", "lnPayload", "mass")
        assert mass == pytest.approx(2200.0, abs=0.5)


# ===== Delta-V Budget Tests =====

class TestDeltaV:
    EXPECTED_TV_DV = 321.0 * G0 * math.log(17068.0 / 11668.0)
    EXPECTED_LN_DV = 315.0 * G0 * math.log(11060.0 / 3260.0)

    def test_tv_specific_impulse(self, report):
        isp = nav(report, "delta_v_budget", "transferVehicle",
                  "specificImpulse")
        assert isp == pytest.approx(321.0, abs=0.1)

    def test_tv_initial_mass(self, report):
        m = nav(report, "delta_v_budget", "transferVehicle", "initialMass")
        assert m == pytest.approx(17068.0, abs=0.5)

    def test_tv_final_mass(self, report):
        m = nav(report, "delta_v_budget", "transferVehicle", "finalMass")
        assert m == pytest.approx(11668.0, abs=0.5)

    def test_tv_delta_v(self, report):
        dv = nav(report, "delta_v_budget", "transferVehicle", "deltaV")
        assert dv == pytest.approx(self.EXPECTED_TV_DV, abs=1.0)

    def test_ln_specific_impulse(self, report):
        isp = nav(report, "delta_v_budget", "lander", "specificImpulse")
        assert isp == pytest.approx(315.0, abs=0.1)

    def test_ln_initial_mass(self, report):
        m = nav(report, "delta_v_budget", "lander", "initialMass")
        assert m == pytest.approx(11060.0, abs=0.5)

    def test_ln_final_mass(self, report):
        m = nav(report, "delta_v_budget", "lander", "finalMass")
        assert m == pytest.approx(3260.0, abs=0.5)

    def test_ln_delta_v(self, report):
        dv = nav(report, "delta_v_budget", "lander", "deltaV")
        assert dv == pytest.approx(self.EXPECTED_LN_DV, abs=1.0)

    def test_total_delta_v(self, report):
        total = report["delta_v_budget"]["totalDeltaV"]
        expected = self.EXPECTED_TV_DV + self.EXPECTED_LN_DV
        assert total == pytest.approx(expected, abs=2.0)


# ===== Power Budget Tests =====

class TestPowerBudget:
    def test_tv_generation(self, report):
        val = nav(report, "power_budget", "transferVehicle", "generation")
        assert val == pytest.approx(2880.0, abs=0.5)

    def test_tv_consumption(self, report):
        val = nav(report, "power_budget", "transferVehicle", "consumption")
        assert val == pytest.approx(325.0, abs=0.5)

    def test_tv_margin(self, report):
        val = nav(report, "power_budget", "transferVehicle", "margin")
        assert val == pytest.approx(2555.0, abs=0.5)

    def test_ln_generation(self, report):
        val = nav(report, "power_budget", "lander", "generation")
        assert val == pytest.approx(4220.0, abs=0.5)

    def test_ln_consumption(self, report):
        val = nav(report, "power_budget", "lander", "consumption")
        assert val == pytest.approx(470.0, abs=0.5)

    def test_ln_margin(self, report):
        val = nav(report, "power_budget", "lander", "margin")
        assert val == pytest.approx(3750.0, abs=0.5)


# ===== Requirements Verification Tests =====

class TestRequirements:
    ALL_REQ_IDS = [
        "REQ-SYS-001", "REQ-TV-001", "REQ-LN-001",
        "REQ-TV-DV-001", "REQ-LN-DV-001",
        "REQ-TV-PWR-001", "REQ-LN-PWR-001", "REQ-PAY-001"
    ]

    def test_all_requirements_present(self, report):
        rv = report["requirements_verification"]
        for rid in self.ALL_REQ_IDS:
            assert rid in rv, f"Missing requirement {rid}"

    def test_req_sys_001_fails(self, report):
        req = report["requirements_verification"]["REQ-SYS-001"]
        assert req["status"] == "FAIL"
        assert req["actual"] == pytest.approx(17068.0, abs=0.5)
        assert req["limit"] == pytest.approx(16000.0, abs=0.5)

    def test_req_tv_001_passes(self, report):
        req = report["requirements_verification"]["REQ-TV-001"]
        assert req["status"] == "PASS"
        assert req["actual"] == pytest.approx(608.0, abs=0.5)
        assert req["limit"] == pytest.approx(700.0, abs=0.5)

    def test_req_ln_001_passes(self, report):
        req = report["requirements_verification"]["REQ-LN-001"]
        assert req["status"] == "PASS"
        assert req["actual"] == pytest.approx(3260.0, abs=0.5)
        assert req["limit"] == pytest.approx(3500.0, abs=0.5)

    def test_req_tv_dv_001_fails(self, report):
        req = report["requirements_verification"]["REQ-TV-DV-001"]
        assert req["status"] == "FAIL"
        expected_dv = 321.0 * G0 * math.log(17068.0 / 11668.0)
        assert req["actual"] == pytest.approx(expected_dv, abs=1.0)
        assert req["limit"] == pytest.approx(1250.0, abs=0.5)

    def test_req_ln_dv_001_passes(self, report):
        req = report["requirements_verification"]["REQ-LN-DV-001"]
        assert req["status"] == "PASS"
        expected_dv = 315.0 * G0 * math.log(11060.0 / 3260.0)
        assert req["actual"] == pytest.approx(expected_dv, abs=1.0)
        assert req["limit"] == pytest.approx(3600.0, abs=0.5)

    def test_req_tv_pwr_001_passes(self, report):
        req = report["requirements_verification"]["REQ-TV-PWR-001"]
        assert req["status"] == "PASS"
        assert req["actual"] == pytest.approx(2555.0, abs=0.5)

    def test_req_ln_pwr_001_passes(self, report):
        req = report["requirements_verification"]["REQ-LN-PWR-001"]
        assert req["status"] == "PASS"
        assert req["actual"] == pytest.approx(3750.0, abs=0.5)

    def test_req_pay_001_passes(self, report):
        req = report["requirements_verification"]["REQ-PAY-001"]
        assert req["status"] == "PASS"
        assert req["actual"] == pytest.approx(2200.0, abs=0.5)
        assert req["limit"] == pytest.approx(2000.0, abs=0.5)

    def test_exactly_two_failures(self, report):
        rv = report["requirements_verification"]
        failures = [rid for rid in self.ALL_REQ_IDS
                    if rv[rid]["status"] == "FAIL"]
        assert len(failures) == 2
        assert set(failures) == {"REQ-SYS-001", "REQ-TV-DV-001"}


# ===== Traceability Tests =====

class TestTraceability:
    def test_all_requirements_in_traceability(self, report):
        tr = report["traceability"]
        for rid in TestRequirements.ALL_REQ_IDS:
            assert rid in tr, f"Missing {rid} in traceability"

    def test_req_sys_001_traceability_gap(self, report):
        tr = report["traceability"]["REQ-SYS-001"]
        assert len(tr["satisfiedBy"]) == 0

    def test_req_tv_001_has_traceability(self, report):
        tr = report["traceability"]["REQ-TV-001"]
        assert len(tr["satisfiedBy"]) > 0
        assert any("transferVehicle" in s for s in tr["satisfiedBy"])

    def test_req_ln_001_has_traceability(self, report):
        tr = report["traceability"]["REQ-LN-001"]
        assert len(tr["satisfiedBy"]) > 0
        assert any("lander" in s for s in tr["satisfiedBy"])

    def test_req_tv_dv_has_traceability(self, report):
        tr = report["traceability"]["REQ-TV-DV-001"]
        assert len(tr["satisfiedBy"]) > 0
        assert any("tvPropulsion" in s for s in tr["satisfiedBy"])

    def test_req_ln_dv_has_traceability(self, report):
        tr = report["traceability"]["REQ-LN-DV-001"]
        assert len(tr["satisfiedBy"]) > 0
        assert any("lnPropulsion" in s for s in tr["satisfiedBy"])

    def test_req_pay_has_traceability(self, report):
        tr = report["traceability"]["REQ-PAY-001"]
        assert len(tr["satisfiedBy"]) > 0
        assert any("lnPayload" in s for s in tr["satisfiedBy"])

    def test_only_one_traceability_gap(self, report):
        tr = report["traceability"]
        gaps = [rid for rid in TestRequirements.ALL_REQ_IDS
                if len(tr[rid]["satisfiedBy"]) == 0]
        assert gaps == ["REQ-SYS-001"]


# ===== Derivation Chain Tests =====

class TestDerivationChains:
    def test_derivation_chains_key_exists(self, report):
        assert "derivation_chains" in report

    def test_derivation_chains_count(self, report):
        dc = report["derivation_chains"]
        assert len(dc) == 2

    def test_tv_mass_derived(self, report):
        dc = report["derivation_chains"]
        assert "tvMassDerived" in dc
        assert "systemMassReq" in dc["tvMassDerived"]

    def test_ln_mass_derived(self, report):
        dc = report["derivation_chains"]
        assert "lnMassDerived" in dc
        assert "systemMassReq" in dc["lnMassDerived"]


# ===== SQLite Database Tests =====

class TestDatabase:
    def test_database_exists(self, db):
        assert db is not None

    def test_tables_exist(self, db):
        tables = {row[0] for row in
                  db.execute(
                      "SELECT name FROM sqlite_master WHERE type='table'"
                  ).fetchall()}
        expected = {"parts", "attributes", "requirements",
                    "req_attributes", "satisfy_links", "derive_links"}
        assert expected.issubset(tables)

    def test_parts_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
        assert count == 27

    def test_root_part_is_selene(self, db):
        roots = db.execute(
            "SELECT name FROM parts WHERE parent_id IS NULL"
        ).fetchall()
        assert len(roots) == 1
        assert roots[0]["name"] == "seleneSystem"

    def test_transfer_vehicle_parent(self, db):
        row = db.execute("""
            SELECT p.name, parent.name as parent_name
            FROM parts p JOIN parts parent ON p.parent_id = parent.id
            WHERE p.name = 'transferVehicle'
        """).fetchone()
        assert row is not None
        assert row["parent_name"] == "seleneSystem"

    def test_lander_parent(self, db):
        row = db.execute("""
            SELECT p.name, parent.name as parent_name
            FROM parts p JOIN parts parent ON p.parent_id = parent.id
            WHERE p.name = 'lander'
        """).fetchone()
        assert row is not None
        assert row["parent_name"] == "seleneSystem"

    def test_tv_structure_mass_attr(self, db):
        row = db.execute("""
            SELECT a.attr_value FROM attributes a
            JOIN parts p ON a.part_id = p.id
            WHERE p.name = 'tvStructure' AND a.attr_name = 'mass'
        """).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(320.0, abs=0.1)

    def test_tv_propellant_consumable(self, db):
        row = db.execute("""
            SELECT a.attr_value FROM attributes a
            JOIN parts p ON a.part_id = p.id
            WHERE p.name = 'tvPropellant' AND a.attr_name = 'isConsumable'
        """).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(1.0, abs=0.01)

    def test_requirements_count(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM requirements"
        ).fetchone()[0]
        assert count == 8

    def test_req_ids_present(self, db):
        req_ids = {row[0] for row in
                   db.execute("SELECT req_id FROM requirements").fetchall()}
        expected = {"REQ-SYS-001", "REQ-TV-001", "REQ-LN-001",
                    "REQ-TV-DV-001", "REQ-LN-DV-001",
                    "REQ-TV-PWR-001", "REQ-LN-PWR-001", "REQ-PAY-001"}
        assert req_ids == expected

    def test_satisfy_links_count(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM satisfy_links"
        ).fetchone()[0]
        assert count == 7

    def test_derive_links_count(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM derive_links"
        ).fetchone()[0]
        assert count == 2

    def test_derive_link_content(self, db):
        rows = db.execute(
            "SELECT child_req_name, parent_req_name FROM derive_links"
        ).fetchall()
        names = {(r["child_req_name"], r["parent_req_name"]) for r in rows}
        assert ("tvMassDerived", "systemMassReq") in names
        assert ("lnMassDerived", "systemMassReq") in names

    def test_leaf_part_count(self, db):
        count = db.execute("""
            SELECT COUNT(*) FROM parts p
            WHERE NOT EXISTS (
                SELECT 1 FROM parts c WHERE c.parent_id = p.id
            )
        """).fetchone()[0]
        assert count == 20

    def test_propulsive_stage_type(self, db):
        rows = db.execute(
            "SELECT name FROM parts WHERE type_name = 'PropulsiveStage'"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert "tvPropulsion" in names
        assert "lnPropulsion" in names


# ===== DOT Graph Tests =====

class TestDotGraph:
    def test_dot_file_exists(self, dot_content):
        assert len(dot_content) > 0

    def test_dot_is_digraph(self, dot_content):
        assert "digraph" in dot_content

    def test_dot_contains_all_req_ids(self, dot_content):
        for rid in TestRequirements.ALL_REQ_IDS:
            assert rid in dot_content, f"Missing {rid} in DOT file"

    def test_dot_has_edges(self, dot_content):
        arrow_count = dot_content.count("->")
        assert arrow_count >= 7, \
            f"Expected at least 7 edges, found {arrow_count}"

    def test_dot_valid_syntax(self, dot_content):
        result = subprocess.run(
            ['dot', '-Tcanon', DOT_PATH],
            capture_output=True, timeout=30)
        assert result.returncode == 0, \
            f"DOT syntax error: {result.stderr.decode()[:500]}"

    def test_dot_distinguishes_pass_fail(self, dot_content):
        colors = re.findall(
            r'fillcolor\s*=\s*"?([^"\s\]]+)"?', dot_content)
        unique_colors = set(c.lower() for c in colors)
        assert len(unique_colors) >= 2, \
            f"Expected at least 2 distinct fill colors for pass/fail, " \
            f"found {unique_colors}"

    def test_dot_shows_gap(self, dot_content):
        content_lower = dot_content.lower()
        has_gap = any(term in content_lower for term in [
            'gap', 'unsatisfied', 'missing', 'no link',
            'no satisfy', 'unlinked', 'orphan', 'not satisfied'])
        assert has_gap, "DOT file should indicate traceability gaps"

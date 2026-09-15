
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
import pytest


# ---------------------------------------------------------------------------
# Independent reference implementation (ground-truth from raw XML)
# ---------------------------------------------------------------------------

def _find_table_file(data_dir, table_id):
    """Locate the XML file for a given SOA table ID by parsing metadata."""
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".xml"):
            continue
        path = os.path.join(data_dir, fname)
        tree = ET.parse(path)
        root = tree.getroot()
        tid = root.find(".//TableIdentity")
        if tid is not None and int(tid.text.strip()) == table_id:
            return path
    raise FileNotFoundError(f"Table ID {table_id} not found in {data_dir}")


def _parse_select_ultimate(xml_path):
    """Parse a VBT select-and-ultimate XTbML file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    tables = root.findall("Table")

    select = {}
    for age_axis in tables[0].findall("Values/Axis"):
        age = int(age_axis.attrib["t"])
        select[age] = {}
        inner = age_axis.find("Axis")
        for y in inner.findall("Y"):
            dur = int(y.attrib["t"])
            select[age][dur] = float(y.text)

    ultimate = {}
    for y in tables[1].findall("Values/Axis/Y"):
        age = int(y.attrib["t"])
        ultimate[age] = float(y.text)

    return select, ultimate


def _parse_improvement(xml_path):
    """Parse an MP improvement-scale XTbML file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    scale = {}
    for age_axis in root.findall(".//Table/Values/Axis"):
        age = int(age_axis.attrib["t"])
        scale[age] = {}
        inner = age_axis.find("Axis")
        for y in inner.findall("Y"):
            yr = int(y.attrib["t"])
            scale[age][yr] = float(y.text)
    return scale


def _get_improvement(scale, age, year):
    """Get improvement factor; years > 2037 use 2037 value."""
    if age not in scale:
        return 0.0
    age_data = scale[age]
    if year in age_data:
        return age_data[year]
    if year > 2037:
        return age_data.get(2037, 0.0)
    return 0.0


def _project_qx(q_base, scale, attained_age, calendar_year, base_year=2015):
    """Apply cumulative improvement to a base mortality rate."""
    factor = 1.0
    for t in range(base_year + 1, calendar_year + 1):
        imp = _get_improvement(scale, attained_age, t)
        factor *= (1.0 - imp)
    return q_base * factor


def _base_rate(select, ultimate, issue_age, duration):
    """Look up base mortality rate: select if duration <= 25, else ultimate."""
    if duration <= 25 and issue_age in select and duration in select[issue_age]:
        return select[issue_age][duration]
    attained_age = issue_age + duration - 1
    return ultimate[attained_age]


def _compute_annuity_due(projected_qx, interest_rate):
    """Compute temporary life annuity-due: sum of k_p_x * v^k."""
    v = 1.0 / (1.0 + interest_rate)
    annuity = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        annuity += kpx * v ** k
        kpx *= (1.0 - qx)
    return annuity


def _compute_insurance_pv(projected_qx, interest_rate):
    """Compute PV of term insurance: sum of k_p_x * q[k] * v^(k+1)."""
    v = 1.0 / (1.0 + interest_rate)
    insurance = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        insurance += kpx * qx * v ** (k + 1)
        kpx *= (1.0 - qx)
    return insurance


def _compute_valuation(select, ultimate, scale, val, base_year=2015,
                       rate_override=None):
    """Independently compute all valuation outputs for a single policy."""
    ia = val["issue_age"]
    iy = val["issue_year"]
    term = val["term_years"]
    i_rate = rate_override if rate_override is not None else val["annual_interest_rate"]
    vy = val["valuation_year"]
    fa = val["face_amount"]

    elapsed = vy - iy
    remaining = term - elapsed

    # Projected qx at valuation
    proj_qx = []
    for k in range(remaining):
        dur = elapsed + k + 1
        att_age = ia + elapsed + k
        cal_yr = vy + k
        qb = _base_rate(select, ultimate, ia, dur)
        proj_qx.append(_project_qx(qb, scale, att_age, cal_yr, base_year))

    annuity = _compute_annuity_due(proj_qx, i_rate)
    insurance = _compute_insurance_pv(proj_qx, i_rate)

    # At-issue projected qx for full term
    issue_qx = []
    for k in range(term):
        dur = k + 1
        att_age = ia + k
        cal_yr = iy + k
        qb = _base_rate(select, ultimate, ia, dur)
        issue_qx.append(_project_qx(qb, scale, att_age, cal_yr, base_year))

    ann_issue = _compute_annuity_due(issue_qx, i_rate)
    ins_issue = _compute_insurance_pv(issue_qx, i_rate)

    premium = ins_issue / ann_issue
    reserve = insurance - premium * annuity

    return {
        "projected_qx": proj_qx,
        "annuity_due": annuity,
        "insurance_pv": insurance,
        "annual_premium": premium,
        "reserve": reserve,
        "face_amount": fa,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def parsed_tables(config):
    data_dir = config["data_directory"]
    mort_path = _find_table_file(data_dir, config["valuations"][0]["table_id"])
    imp_path = _find_table_file(data_dir, config["valuations"][0]["improvement_table_id"])
    sel, ult = _parse_select_ultimate(mort_path)
    scale = _parse_improvement(imp_path)
    return sel, ult, scale


@pytest.fixture(scope="session")
def expected(config, parsed_tables):
    sel, ult, scale = parsed_tables
    by = config["base_year"]
    stress = config["stress_bps"]
    results = {}
    total = 0.0
    total_up = 0.0
    total_down = 0.0
    for val in config["valuations"]:
        r = _compute_valuation(sel, ult, scale, val, by)
        base_rate = val["annual_interest_rate"]
        r_up = _compute_valuation(sel, ult, scale, val, by,
                                   rate_override=base_rate + stress * 0.0001)
        r_down = _compute_valuation(sel, ult, scale, val, by,
                                     rate_override=base_rate - stress * 0.0001)
        results[val["id"]] = {
            **r,
            "reserve_up": r_up["reserve"],
            "reserve_down": r_down["reserve"],
        }
        total += r["face_amount"] * r["reserve"]
        total_up += r["face_amount"] * r_up["reserve"]
        total_down += r["face_amount"] * r_down["reserve"]
    results["total_reserve"] = total
    results["total_reserve_up"] = total_up
    results["total_reserve_down"] = total_down
    return results


@pytest.fixture(scope="session")
def agent_results():
    path = "/app/results.json"
    assert os.path.isfile(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


ALL_IDS = ["V1", "V2", "V3", "V4", "V5"]


def _rel_err(actual, expected_val):
    if expected_val == 0:
        return abs(actual)
    return abs(actual - expected_val) / abs(expected_val)


# ---------------------------------------------------------------------------
# Tests — SQLite Database Structure and Content
# ---------------------------------------------------------------------------

class TestDatabaseStructure:
    """Verify the SQLite database exists with correct schema and content."""

    def test_database_exists(self):
        assert os.path.isfile("/app/mortality.db"), "mortality.db must exist"

    def test_database_tables(self):
        conn = sqlite3.connect("/app/mortality.db")
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        conn.close()
        for t in ["table_metadata", "select_rates", "ultimate_rates",
                   "improvement_factors"]:
            assert t in tables, f"Missing table: {t}"

    def test_metadata_rows(self):
        conn = sqlite3.connect("/app/mortality.db")
        count = conn.execute("SELECT COUNT(*) FROM table_metadata").fetchone()[0]
        conn.close()
        assert count >= 2, f"Expected at least 2 metadata rows, got {count}"

    def test_select_rates_count(self):
        """VBT 3265 should have 78 ages * 25 durations = 1950 select entries."""
        conn = sqlite3.connect("/app/mortality.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM select_rates WHERE table_id=3265"
        ).fetchone()[0]
        conn.close()
        assert count == 1950, f"Expected 1950 select_rates for VBT 3265, got {count}"

    def test_ultimate_rates_count(self):
        """VBT 3265 should have 103 ultimate entries (ages 18-120)."""
        conn = sqlite3.connect("/app/mortality.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM ultimate_rates WHERE table_id=3265"
        ).fetchone()[0]
        conn.close()
        assert count == 103, f"Expected 103 ultimate_rates for VBT 3265, got {count}"

    def test_improvement_factors_count(self):
        """MP-2021 (3612) should have 101 ages * 87 years = 8787 entries."""
        conn = sqlite3.connect("/app/mortality.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM improvement_factors WHERE table_id=3612"
        ).fetchone()[0]
        conn.close()
        assert count == 8787, (
            f"Expected 8787 improvement_factors for MP-2021, got {count}"
        )

    def test_improvement_factors_are_float(self):
        """Improvement factors must be stored as real numbers, not truncated."""
        conn = sqlite3.connect("/app/mortality.db")
        row = conn.execute(
            "SELECT rate FROM improvement_factors "
            "WHERE table_id=3612 AND age=45 AND year=2020"
        ).fetchone()
        conn.close()
        assert row is not None, "Missing improvement factor age=45, year=2020"
        assert abs(row[0]) > 0.0001, (
            f"Improvement factor appears truncated to {row[0]} — "
            f"check that the column type is REAL, not INTEGER"
        )

    def test_select_rate_spot_check_db(self, parsed_tables):
        """Verify a select rate in DB matches the XML source."""
        sel, _, _ = parsed_tables
        expected_qx = sel[45][1]  # issue_age=45, duration=1
        conn = sqlite3.connect("/app/mortality.db")
        row = conn.execute(
            "SELECT qx FROM select_rates "
            "WHERE table_id=3265 AND issue_age=45 AND duration=1"
        ).fetchone()
        conn.close()
        assert row is not None, "Missing select rate for age=45, dur=1"
        assert abs(row[0] - expected_qx) < 1e-10, (
            f"Select rate mismatch: DB={row[0]}, XML={expected_qx}"
        )

    def test_ultimate_rate_spot_check_db(self, parsed_tables):
        """Verify an ultimate rate in DB matches the XML source."""
        _, ult, _ = parsed_tables
        expected_qx = ult[60]
        conn = sqlite3.connect("/app/mortality.db")
        row = conn.execute(
            "SELECT qx FROM ultimate_rates "
            "WHERE table_id=3265 AND attained_age=60"
        ).fetchone()
        conn.close()
        assert row is not None, "Missing ultimate rate for age=60"
        assert abs(row[0] - expected_qx) < 1e-10, (
            f"Ultimate rate mismatch: DB={row[0]}, XML={expected_qx}"
        )

    def test_improvement_factor_spot_check_db(self, parsed_tables):
        """Verify an improvement factor in DB matches the XML source."""
        _, _, scale = parsed_tables
        expected_rate = scale[55][2025]
        conn = sqlite3.connect("/app/mortality.db")
        row = conn.execute(
            "SELECT rate FROM improvement_factors "
            "WHERE table_id=3612 AND age=55 AND year=2025"
        ).fetchone()
        conn.close()
        assert row is not None, "Missing improvement factor age=55, year=2025"
        assert abs(row[0] - expected_rate) < 1e-10, (
            f"Improvement factor mismatch: DB={row[0]}, XML={expected_rate}"
        )

    def test_no_duplicate_select_rates(self):
        """select_rates should not have duplicate (table_id, issue_age, duration)."""
        conn = sqlite3.connect("/app/mortality.db")
        dupes = conn.execute(
            "SELECT table_id, issue_age, duration, COUNT(*) as cnt "
            "FROM select_rates GROUP BY table_id, issue_age, duration "
            "HAVING cnt > 1"
        ).fetchall()
        conn.close()
        assert len(dupes) == 0, (
            f"Found {len(dupes)} duplicate select_rates entries"
        )


# ---------------------------------------------------------------------------
# Tests — Results Structure
# ---------------------------------------------------------------------------

class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json must exist"

    def test_top_level_keys(self, agent_results, config):
        for val in config["valuations"]:
            assert val["id"] in agent_results, f"Missing key {val['id']}"
        assert "total_reserve" in agent_results
        assert "total_reserve_up" in agent_results
        assert "total_reserve_down" in agent_results

    def test_valuation_fields(self, agent_results, config):
        required = {"projected_qx", "annuity_due", "insurance_pv",
                     "annual_premium", "reserve", "reserve_up", "reserve_down"}
        for val in config["valuations"]:
            entry = agent_results[val["id"]]
            for field in required:
                assert field in entry, f"{val['id']} missing {field}"

    def test_projected_qx_lengths(self, agent_results, config):
        for val in config["valuations"]:
            remaining = val["term_years"] - (val["valuation_year"] - val["issue_year"])
            qx = agent_results[val["id"]]["projected_qx"]
            assert len(qx) == remaining, (
                f"{val['id']}: expected {remaining} qx values, got {len(qx)}"
            )


# ---------------------------------------------------------------------------
# Tests — Actuarial Constraints
# ---------------------------------------------------------------------------

class TestActuarialConstraints:
    def test_qx_bounds(self, agent_results, config):
        for val in config["valuations"]:
            for k, q in enumerate(agent_results[val["id"]]["projected_qx"]):
                assert 0 < q < 1, f"{val['id']} qx[{k}]={q} out of (0,1)"

    def test_annuity_bounds(self, agent_results, config):
        for val in config["valuations"]:
            remaining = val["term_years"] - (val["valuation_year"] - val["issue_year"])
            ann = agent_results[val["id"]]["annuity_due"]
            assert 1.0 <= ann <= remaining, (
                f"{val['id']} annuity_due={ann} out of [1, {remaining}]"
            )

    def test_insurance_pv_positive(self, agent_results, config):
        for val in config["valuations"]:
            ins = agent_results[val["id"]]["insurance_pv"]
            assert ins > 0, f"{val['id']} insurance_pv should be positive"

    def test_stress_ordering(self, agent_results, config):
        """Higher interest rate should reduce reserve for standard term."""
        for val in config["valuations"]:
            entry = agent_results[val["id"]]
            assert entry["reserve_up"] < entry["reserve_down"], (
                f"{val['id']}: reserve_up should be < reserve_down "
                f"(got {entry['reserve_up']} vs {entry['reserve_down']})"
            )


# ---------------------------------------------------------------------------
# Tests — Projected Mortality Rates
# ---------------------------------------------------------------------------

class TestProjectedQx:
    TOL = 1e-6

    @pytest.mark.parametrize("vid", ALL_IDS)
    def test_projected_qx_values(self, agent_results, expected, vid):
        exp_qx = expected[vid]["projected_qx"]
        act_qx = agent_results[vid]["projected_qx"]
        assert len(act_qx) == len(exp_qx), f"{vid}: length mismatch"
        for k, (a, e) in enumerate(zip(act_qx, exp_qx)):
            assert _rel_err(a, e) < self.TOL, (
                f"{vid} qx[{k}]: got {a}, expected {e}, rel_err={_rel_err(a, e)}"
            )


# ---------------------------------------------------------------------------
# Tests — Annuity-due Values
# ---------------------------------------------------------------------------

class TestAnnuityValues:
    TOL = 1e-6

    @pytest.mark.parametrize("vid", ALL_IDS)
    def test_annuity_due(self, agent_results, expected, vid):
        a = agent_results[vid]["annuity_due"]
        e = expected[vid]["annuity_due"]
        assert _rel_err(a, e) < self.TOL, (
            f"{vid} annuity_due: got {a}, expected {e}"
        )


# ---------------------------------------------------------------------------
# Tests — Insurance PV
# ---------------------------------------------------------------------------

class TestInsurancePV:
    TOL = 1e-6

    @pytest.mark.parametrize("vid", ALL_IDS)
    def test_insurance_pv(self, agent_results, expected, vid):
        a = agent_results[vid]["insurance_pv"]
        e = expected[vid]["insurance_pv"]
        assert _rel_err(a, e) < self.TOL, (
            f"{vid} insurance_pv: got {a}, expected {e}"
        )


# ---------------------------------------------------------------------------
# Tests — Annual Premium
# ---------------------------------------------------------------------------

class TestAnnualPremium:
    TOL = 1e-6

    @pytest.mark.parametrize("vid", ALL_IDS)
    def test_annual_premium(self, agent_results, expected, vid):
        a = agent_results[vid]["annual_premium"]
        e = expected[vid]["annual_premium"]
        assert _rel_err(a, e) < self.TOL, (
            f"{vid} annual_premium: got {a}, expected {e}"
        )


# ---------------------------------------------------------------------------
# Tests — Reserves (base, up, down)
# ---------------------------------------------------------------------------

class TestReserve:
    TOL = 1e-6

    @pytest.mark.parametrize("vid", ALL_IDS)
    def test_reserve(self, agent_results, expected, vid):
        a = agent_results[vid]["reserve"]
        e = expected[vid]["reserve"]
        assert _rel_err(a, e) < self.TOL, (
            f"{vid} reserve: got {a}, expected {e}"
        )

    @pytest.mark.parametrize("vid", ALL_IDS)
    def test_reserve_up(self, agent_results, expected, vid):
        a = agent_results[vid]["reserve_up"]
        e = expected[vid]["reserve_up"]
        assert _rel_err(a, e) < self.TOL, (
            f"{vid} reserve_up: got {a}, expected {e}"
        )

    @pytest.mark.parametrize("vid", ALL_IDS)
    def test_reserve_down(self, agent_results, expected, vid):
        a = agent_results[vid]["reserve_down"]
        e = expected[vid]["reserve_down"]
        assert _rel_err(a, e) < self.TOL, (
            f"{vid} reserve_down: got {a}, expected {e}"
        )


# ---------------------------------------------------------------------------
# Tests — Total Reserves
# ---------------------------------------------------------------------------

class TestTotalReserve:
    TOL = 1e-6

    def test_total_reserve(self, agent_results, expected):
        a = agent_results["total_reserve"]
        e = expected["total_reserve"]
        assert _rel_err(a, e) < self.TOL, f"total_reserve: got {a}, expected {e}"

    def test_total_reserve_up(self, agent_results, expected):
        a = agent_results["total_reserve_up"]
        e = expected["total_reserve_up"]
        assert _rel_err(a, e) < self.TOL, f"total_reserve_up: got {a}, expected {e}"

    def test_total_reserve_down(self, agent_results, expected):
        a = agent_results["total_reserve_down"]
        e = expected["total_reserve_down"]
        assert _rel_err(a, e) < self.TOL, f"total_reserve_down: got {a}, expected {e}"

    def test_total_reserve_consistency(self, agent_results, config):
        """Verify total_reserve equals sum of face * reserve."""
        total = 0.0
        for val in config["valuations"]:
            entry = agent_results[val["id"]]
            total += val["face_amount"] * entry["reserve"]
        assert _rel_err(agent_results["total_reserve"], total) < 1e-10, (
            "total_reserve must equal sum of face_amount * reserve"
        )


# ---------------------------------------------------------------------------
# Tests — Select/Ultimate Boundary Transitions
# ---------------------------------------------------------------------------

class TestSelectUltimateTransition:
    def test_select_duration_25_in_db(self):
        """Duration 25 must exist in select_rates for typical ages."""
        conn = sqlite3.connect("/app/mortality.db")
        row = conn.execute(
            "SELECT qx FROM select_rates "
            "WHERE table_id=3265 AND issue_age=45 AND duration=25"
        ).fetchone()
        conn.close()
        assert row is not None, "Select table must include duration 25"
        assert row[0] > 0, "Select rate at duration 25 must be positive"

    def test_v2_dur26_uses_ultimate(self, expected, parsed_tables):
        """V2: issue_age=35, term=30. Duration 26+ uses ultimate rates."""
        sel, ult, scale = parsed_tables
        q_base_dur26 = ult[60]  # attained_age = 35 + 25 = 60
        assert q_base_dur26 == pytest.approx(0.00408, abs=1e-10)
        projected = _project_qx(q_base_dur26, scale, 60, 2043, 2015)
        assert 0 < projected < q_base_dur26 * 1.5


# ---------------------------------------------------------------------------
# Tests — Pipeline Integration
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile must exist"

    def test_db_has_real_improvement_factors(self):
        """Improvement factors must not all be zero (checks for INTEGER
        truncation or XPath parsing bugs)."""
        conn = sqlite3.connect("/app/mortality.db")
        row = conn.execute(
            "SELECT AVG(ABS(rate)) FROM improvement_factors WHERE table_id=3612"
        ).fetchone()
        conn.close()
        assert row is not None and row[0] is not None
        assert row[0] > 0.001, (
            f"Average absolute improvement factor is {row[0]} — "
            f"factors appear to be zero or near-zero"
        )

    def test_improvement_factor_range(self):
        """Spot-check improvement factors are in reasonable range."""
        conn = sqlite3.connect("/app/mortality.db")
        rows = conn.execute(
            "SELECT MIN(rate), MAX(rate) FROM improvement_factors "
            "WHERE table_id=3612 AND year >= 2015"
        ).fetchone()
        conn.close()
        assert rows[0] is not None
        assert -0.05 < rows[0], f"Min improvement factor {rows[0]} too negative"
        assert rows[1] < 0.10, f"Max improvement factor {rows[1]} too large"

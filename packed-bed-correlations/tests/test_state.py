
"""Tests for packed-bed reactor analysis pipeline.

Validates pressure drops, minimum fluidization velocities, and terminal
settling velocities stored in SQLite against the fluids library as
reference implementation.
"""

import os
import sqlite3

import pytest
from scipy.optimize import brentq

import fluids.packed_bed as pb
from fluids.drag import v_terminal as ref_v_terminal

# ---------- constants ----------
G = 9.80665
RTOL = 1e-3  # 0.1% relative tolerance
DB_PATH = "/app/results.db"

# ---------- correlation map ----------
# (fluids function, accepts_Dt)
CORR_MAP = {
    "Ergun": (pb.Ergun, False),
    "Kuo_Nydegger": (pb.Kuo_Nydegger, False),
    "Tallmadge": (pb.Tallmadge, False),
    "Jones_Krier": (pb.Jones_Krier, False),
    "Carman": (pb.Carman, False),
    "Hicks": (pb.Hicks, False),
    "Brauer": (pb.Brauer, False),
    "KTA": (pb.KTA, False),
    "Erdim_Akgiray_Demir": (pb.Erdim_Akgiray_Demir, False),
    "Fahien_Schriver": (pb.Fahien_Schriver, False),
    "Idelchik": (pb.Idelchik, False),
    "Harrison_Brunner_Hecker": (pb.Harrison_Brunner_Hecker, True),
    "Montillet_Akkari_Comiti": (pb.Montillet_Akkari_Comiti, True),
}

CORR_NAMES = list(CORR_MAP.keys())
SCENARIO_NAMES = ["aqueous_baseline", "aqueous_walled", "gas_phase", "fine_particles"]


# ---------- helpers ----------

def _ref_dp(name, dp, voidage, vs, rho, mu, L, Dt):
    func, uses_dt = CORR_MAP[name]
    kw = dict(dp=dp, voidage=voidage, vs=vs, rho=rho, mu=mu, L=L)
    if uses_dt:
        kw["Dt"] = Dt
    return func(**kw)


def _ref_vmf(name, dp, voidage, rho, mu, rho_p, Dt):
    func, uses_dt = CORR_MAP[name]
    bed_wt = (1.0 - voidage) * (rho_p - rho) * G

    def obj(vs):
        kw = dict(dp=dp, voidage=voidage, vs=vs, rho=rho, mu=mu, L=1.0)
        if uses_dt:
            kw["Dt"] = Dt
        return func(**kw) - bed_wt

    return brentq(obj, 1e-15, 1e4, xtol=1e-14, rtol=1e-14)


def _load_scenarios():
    import tomllib
    with open("/app/scenarios.toml", "rb") as f:
        data = tomllib.load(f)
    return {s["name"]: s for s in data["scenarios"]}


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def scenarios():
    return _load_scenarios()


@pytest.fixture(scope="module")
def db():
    assert os.path.exists(DB_PATH), f"Database not found at {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


# ---------- structural tests ----------

class TestStructure:
    def test_db_exists(self):
        assert os.path.exists(DB_PATH), "results.db not found"

    def test_tables_exist(self, db):
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "pressure_drops" in tables, "Missing table 'pressure_drops'"
        assert "fluidization" in tables, "Missing table 'fluidization'"
        assert "terminal_velocity" in tables, "Missing table 'terminal_velocity'"

    def test_pressure_drops_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM pressure_drops").fetchone()[0]
        assert count == len(SCENARIO_NAMES) * len(CORR_NAMES), (
            f"Expected {len(SCENARIO_NAMES) * len(CORR_NAMES)} rows, got {count}"
        )

    def test_fluidization_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM fluidization").fetchone()[0]
        assert count == len(SCENARIO_NAMES) * len(CORR_NAMES), (
            f"Expected {len(SCENARIO_NAMES) * len(CORR_NAMES)} rows, got {count}"
        )

    def test_terminal_velocity_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM terminal_velocity").fetchone()[0]
        assert count == len(SCENARIO_NAMES), (
            f"Expected {len(SCENARIO_NAMES)} rows, got {count}"
        )

    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_scenario_in_pressure_drops(self, db, sname):
        count = db.execute(
            "SELECT COUNT(*) FROM pressure_drops WHERE scenario=?", (sname,)
        ).fetchone()[0]
        assert count == len(CORR_NAMES), (
            f"Scenario '{sname}' has {count} pressure drop entries, expected {len(CORR_NAMES)}"
        )

    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_scenario_in_fluidization(self, db, sname):
        count = db.execute(
            "SELECT COUNT(*) FROM fluidization WHERE scenario=?", (sname,)
        ).fetchone()[0]
        assert count == len(CORR_NAMES), (
            f"Scenario '{sname}' has {count} fluidization entries, expected {len(CORR_NAMES)}"
        )

    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_scenario_in_terminal_velocity(self, db, sname):
        row = db.execute(
            "SELECT vt FROM terminal_velocity WHERE scenario=?", (sname,)
        ).fetchone()
        assert row is not None, f"No terminal velocity for scenario '{sname}'"


# ---------- no-fluids-import check ----------

class TestNoFluidsImport:
    def test_no_fluids_import_in_app(self):
        """The solution must not use the fluids package at runtime."""
        for root, dirs, files in os.walk("/app"):
            for fname in files:
                if fname.endswith(".py"):
                    path = os.path.join(root, fname)
                    with open(path) as f:
                        content = f.read()
                    assert "import fluids" not in content and "from fluids" not in content, (
                        f"{path} imports the fluids package"
                    )


# ---------- pressure drop tests ----------

class TestPressureDrops:
    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    @pytest.mark.parametrize("cname", CORR_NAMES)
    def test_dp(self, db, scenarios, sname, cname):
        s = scenarios[sname]
        expected = _ref_dp(
            cname, s["dp"], s["voidage"], s["vs"],
            s["rho_fluid"], s["mu"], s["L"], s.get("Dt"),
        )
        row = db.execute(
            "SELECT value FROM pressure_drops WHERE scenario=? AND correlation=?",
            (sname, cname),
        ).fetchone()
        assert row is not None, f"No result for {cname} in {sname}"
        actual = row[0]
        rel_err = abs(actual - expected) / abs(expected)
        assert rel_err < RTOL, (
            f"{cname} scenario={sname}: got {actual}, expected {expected}, "
            f"rel_err={rel_err:.6e}"
        )


# ---------- minimum fluidization velocity tests ----------

class TestVmf:
    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    @pytest.mark.parametrize("cname", CORR_NAMES)
    def test_vmf(self, db, scenarios, sname, cname):
        s = scenarios[sname]
        expected = _ref_vmf(
            cname, s["dp"], s["voidage"],
            s["rho_fluid"], s["mu"], s["rho_particle"], s.get("Dt"),
        )
        row = db.execute(
            "SELECT vmf FROM fluidization WHERE scenario=? AND correlation=?",
            (sname, cname),
        ).fetchone()
        assert row is not None, f"No vmf for {cname} in {sname}"
        actual = row[0]
        rel_err = abs(actual - expected) / abs(expected)
        assert rel_err < RTOL, (
            f"vmf {cname} scenario={sname}: got {actual}, expected {expected}, "
            f"rel_err={rel_err:.6e}"
        )


# ---------- terminal velocity tests ----------

class TestTerminalVelocity:
    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_vt(self, db, scenarios, sname):
        s = scenarios[sname]
        expected = ref_v_terminal(
            D=s["dp"], rhop=s["rho_particle"],
            rho=s["rho_fluid"], mu=s["mu"],
        )
        row = db.execute(
            "SELECT vt FROM terminal_velocity WHERE scenario=?", (sname,)
        ).fetchone()
        assert row is not None, f"No v_terminal for {sname}"
        actual = row[0]
        rel_err = abs(actual - expected) / abs(expected)
        assert rel_err < RTOL, (
            f"v_terminal scenario={sname}: got {actual}, expected {expected}, "
            f"rel_err={rel_err:.6e}"
        )


# ---------- sanity / physics tests ----------

class TestPhysicsSanity:
    """Basic physics checks independent of the fluids library."""

    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_dp_positive(self, db, sname):
        rows = db.execute(
            "SELECT correlation, value FROM pressure_drops WHERE scenario=?",
            (sname,),
        ).fetchall()
        for cname, val in rows:
            assert val > 0, f"{cname} gave non-positive dP in {sname}"

    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_vmf_positive(self, db, sname):
        rows = db.execute(
            "SELECT correlation, vmf FROM fluidization WHERE scenario=?",
            (sname,),
        ).fetchall()
        for cname, val in rows:
            assert val > 0, f"{cname} gave non-positive vmf in {sname}"

    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_vt_positive(self, db, sname):
        row = db.execute(
            "SELECT vt FROM terminal_velocity WHERE scenario=?", (sname,)
        ).fetchone()
        assert row[0] > 0, f"Non-positive v_terminal in {sname}"

    @pytest.mark.parametrize("sname", SCENARIO_NAMES)
    def test_vmf_less_than_vt(self, db, sname):
        """Fluidization velocity should be less than terminal velocity."""
        vt = db.execute(
            "SELECT vt FROM terminal_velocity WHERE scenario=?", (sname,)
        ).fetchone()[0]
        rows = db.execute(
            "SELECT correlation, vmf FROM fluidization WHERE scenario=?",
            (sname,),
        ).fetchall()
        for cname, vmf_val in rows:
            assert vmf_val < vt, (
                f"vmf ({cname}={vmf_val}) >= v_terminal ({vt}) in {sname}"
            )

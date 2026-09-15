
import json
import math
import os
import subprocess
import tempfile

import pytest


def run_catreactor(subcommand, input_data):
    """Run catreactor.py with the given subcommand and input data, return parsed output."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    ) as f:
        json.dump(input_data, f)
        input_path = f.name

    output_path = input_path + ".out"

    result = subprocess.run(
        ["python3", "/app/catreactor.py", subcommand, input_path, output_path],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, (
        f"catreactor {subcommand} failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    with open(output_path) as f:
        output = json.load(f)

    os.unlink(input_path)
    os.unlink(output_path)

    return output


# ---------------------------------------------------------------------------
# LHHW Rate Tests
# ---------------------------------------------------------------------------


class TestLHHWRate:
    def test_unimolecular_surface_rxn(self):
        """A -> M + N, surface reaction controlling (dual-site)."""
        inp = {
            "mechanism_type": "unimolecular",
            "reactants": ["A"],
            "k_sr": 0.1,
            "species": {
                "A": {"K": 2.0, "C": 0.5},
                "M": {"K": 0.5, "C": 0.1},
                "N": {"K": 0.3, "C": 0.05},
            },
        }
        out = run_catreactor("rate", inp)
        # denom = 1 + 2.0*0.5 + 0.5*0.1 + 0.3*0.05 = 2.065
        # rate = 0.1 * 2.0 * 0.5 / 2.065^2 = 0.1 / 4.264225
        expected = 0.1 * 2.0 * 0.5 / (2.065 ** 2)
        assert abs(out["rate"] - expected) < 1e-4, (
            f"Expected {expected}, got {out['rate']}"
        )

    def test_bimolecular_no_product_adsorption(self):
        """A + B -> C, surface rxn controlling, product C NOT adsorbed."""
        inp = {
            "mechanism_type": "bimolecular",
            "reactants": ["A", "B"],
            "k_sr": 0.05,
            "species": {
                "A": {"K": 1.5, "C": 0.3},
                "B": {"K": 2.5, "C": 0.4},
            },
        }
        out = run_catreactor("rate", inp)
        # denom = 1 + 1.5*0.3 + 2.5*0.4 = 2.45
        # rate = 0.05 * 1.5*2.5 * 0.3*0.4 / 2.45^2 = 0.0225 / 6.0025
        expected = 0.05 * 1.5 * 2.5 * 0.3 * 0.4 / (2.45 ** 2)
        assert abs(out["rate"] - expected) < 1e-4

    def test_bimolecular_with_product_adsorption(self):
        """A + B -> C, surface rxn controlling, product C IS adsorbed."""
        inp = {
            "mechanism_type": "bimolecular",
            "reactants": ["A", "B"],
            "k_sr": 0.05,
            "species": {
                "A": {"K": 1.5, "C": 0.3},
                "B": {"K": 2.5, "C": 0.4},
                "C": {"K": 0.8, "C": 0.2},
            },
        }
        out = run_catreactor("rate", inp)
        # denom = 1 + 0.45 + 1.0 + 0.16 = 2.61
        # rate = 0.0225 / 2.61^2 = 0.0225 / 6.8121
        denom = 1 + 1.5 * 0.3 + 2.5 * 0.4 + 0.8 * 0.2
        expected = 0.05 * 1.5 * 2.5 * 0.3 * 0.4 / (denom ** 2)
        assert abs(out["rate"] - expected) < 1e-4


# ---------------------------------------------------------------------------
# Arrhenius Test
# ---------------------------------------------------------------------------


class TestArrhenius:
    def test_no2_decomposition(self):
        """Fit Arrhenius to NO2 decomposition data."""
        inp = {
            "temperatures": [592.0, 603.0, 627.0, 651.5, 656.0],
            "rate_constants": [522.0, 755.0, 1700.0, 4020.0, 5030.0],
            "R": 8.314,
        }
        out = run_catreactor("arrhenius", inp)

        # Independently compute the expected OLS result
        T = inp["temperatures"]
        k_vals = inp["rate_constants"]
        R = inp["R"]
        n = len(T)
        x = [1.0 / t for t in T]
        y = [math.log(ki) for ki in k_vals]
        sx = sum(x)
        sy = sum(y)
        sxy = sum(a * b for a, b in zip(x, y))
        sx2 = sum(a * a for a in x)
        slope = (n * sxy - sx * sy) / (n * sx2 - sx ** 2)
        intercept = (sy - slope * sx) / n
        E_expected = -slope * R
        k0_expected = math.exp(intercept)
        y_mean = sy / n
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        ss_res = sum((yi - intercept - slope * xi) ** 2 for xi, yi in zip(x, y))
        r2_expected = 1.0 - ss_res / ss_tot

        # Check activation energy within 0.5%
        assert abs(out["activation_energy"] - E_expected) / E_expected < 0.005, (
            f"E expected ~{E_expected:.1f}, got {out['activation_energy']:.1f}"
        )
        # Check pre-exponential within 5% (exponentially sensitive)
        assert abs(out["pre_exponential_factor"] - k0_expected) / k0_expected < 0.05
        # R-squared must be high
        assert out["r_squared"] > 0.99


# ---------------------------------------------------------------------------
# Reactor Network Tests
# ---------------------------------------------------------------------------


class TestNetworkSingleReactor:
    def test_pfr_first_order_liquid(self):
        """Single PFR, 1st order, liquid phase."""
        inp = {
            "kinetics": {"order": 1, "rate_constant": 0.1, "epsilon_A": 0.0},
            "feed": {"C_A0": 2.0, "volumetric_flow_rate": 1.0},
            "stages": [
                {"type": "single", "reactor": {"type": "PFR", "volume": 10.0}}
            ],
        }
        out = run_catreactor("network", inp)
        # tau=10, k*tau=1, X_A = 1 - exp(-1)
        expected_ca = 2.0 * math.exp(-1.0)
        expected_xa = 1.0 - math.exp(-1.0)
        assert abs(out["outlet"]["C_A"] - expected_ca) < 1e-3
        assert abs(out["outlet"]["X_A"] - expected_xa) < 1e-3

    def test_cstr_second_order_liquid(self):
        """Single CSTR, 2nd order, liquid phase."""
        inp = {
            "kinetics": {"order": 2, "rate_constant": 0.5, "epsilon_A": 0.0},
            "feed": {"C_A0": 1.0, "volumetric_flow_rate": 1.0},
            "stages": [
                {"type": "single", "reactor": {"type": "CSTR", "volume": 2.0}}
            ],
        }
        out = run_catreactor("network", inp)
        # k*tau*CA^2 + CA - CA0 = 0  =>  CA^2 + CA - 1 = 0
        # CA = (-1 + sqrt(5)) / 2
        expected_ca = (-1.0 + math.sqrt(5.0)) / 2.0
        expected_xa = 1.0 - expected_ca
        assert abs(out["outlet"]["C_A"] - expected_ca) < 1e-3
        assert abs(out["outlet"]["X_A"] - expected_xa) < 1e-3


class TestNetworkSeries:
    def test_two_cstrs_series_second_order(self):
        """Two CSTRs in series, 2nd order, liquid phase."""
        inp = {
            "kinetics": {"order": 2, "rate_constant": 0.5, "epsilon_A": 0.0},
            "feed": {"C_A0": 1.0, "volumetric_flow_rate": 1.0},
            "stages": [
                {"type": "single", "reactor": {"type": "CSTR", "volume": 2.0}},
                {"type": "single", "reactor": {"type": "CSTR", "volume": 4.0}},
            ],
        }
        out = run_catreactor("network", inp)
        # CSTR 1: CA1 = (-1+sqrt(5))/2 = 0.61803
        ca1 = (-1.0 + math.sqrt(5.0)) / 2.0
        # CSTR 2: 2*CA2^2 + CA2 - ca1 = 0
        # CA2 = (-1 + sqrt(1 + 8*ca1)) / 4
        ca2 = (-1.0 + math.sqrt(1.0 + 8.0 * ca1)) / 4.0
        expected_xa = 1.0 - ca2
        assert abs(out["outlet"]["C_A"] - ca2) < 1e-3
        assert abs(out["outlet"]["X_A"] - expected_xa) < 1e-3
        # Also check intermediate stage
        assert abs(out["stages"][0]["C_A"] - ca1) < 1e-3


class TestNetworkParallel:
    def test_parallel_pfr_cstr_first_order(self):
        """PFR and CSTR in parallel, 1st order, liquid phase."""
        inp = {
            "kinetics": {"order": 1, "rate_constant": 0.2, "epsilon_A": 0.0},
            "feed": {"C_A0": 1.0, "volumetric_flow_rate": 5.0},
            "stages": [
                {
                    "type": "parallel",
                    "branches": [
                        {
                            "reactor": {"type": "PFR", "volume": 10.0},
                            "flow_fraction": 0.4,
                        },
                        {
                            "reactor": {"type": "CSTR", "volume": 20.0},
                            "flow_fraction": 0.6,
                        },
                    ],
                }
            ],
        }
        out = run_catreactor("network", inp)
        # PFR branch: v=2, tau=5, k*tau=1, CA=exp(-1)=0.36788
        ca_pfr = 1.0 * math.exp(-0.2 * 10.0 / (0.4 * 5.0))
        # CSTR branch: v=3, tau=20/3, k*tau=4/3, CA=1/(1+4/3)=3/7
        k_tau_cstr = 0.2 * 20.0 / (0.6 * 5.0)
        ca_cstr = 1.0 / (1.0 + k_tau_cstr)
        # Mix: flow-weighted average
        v_pfr = 0.4 * 5.0
        v_cstr = 0.6 * 5.0
        ca_mix = (v_pfr * ca_pfr + v_cstr * ca_cstr) / (v_pfr + v_cstr)
        expected_xa = 1.0 - ca_mix
        assert abs(out["outlet"]["C_A"] - ca_mix) < 1e-3
        assert abs(out["outlet"]["X_A"] - expected_xa) < 1e-3


class TestNetworkRecycle:
    def test_pfr_recycle_first_order(self):
        """PFR with recycle, 1st order, liquid phase."""
        inp = {
            "kinetics": {"order": 1, "rate_constant": 0.1, "epsilon_A": 0.0},
            "feed": {"C_A0": 1.0, "volumetric_flow_rate": 1.0},
            "stages": [
                {
                    "type": "recycle",
                    "reactor": {"type": "PFR", "volume": 10.0},
                    "recycle_ratio": 2.0,
                }
            ],
        }
        out = run_catreactor("network", inp)
        # Analytical: CA = CA0*exp(-k*tau) / ((1+R) - R*exp(-k*tau))
        # tau = V / (v0*(1+R)) = 10/3
        R_val = 2.0
        k = 0.1
        tau = 10.0 / (1.0 * (1.0 + R_val))
        e_neg_kt = math.exp(-k * tau)
        expected_ca = 1.0 * e_neg_kt / ((1.0 + R_val) - R_val * e_neg_kt)
        expected_xa = 1.0 - expected_ca
        assert abs(out["outlet"]["C_A"] - expected_ca) < 1e-3, (
            f"Expected CA={expected_ca:.5f}, got {out['outlet']['C_A']:.5f}"
        )
        assert abs(out["outlet"]["X_A"] - expected_xa) < 1e-3


class TestNetworkGasPhase:
    def test_pfr_gas_phase_first_order(self):
        """PFR, 1st order, gas phase with epsilon_A=1 (A -> R + S)."""
        inp = {
            "kinetics": {"order": 1, "rate_constant": 0.5, "epsilon_A": 1.0},
            "feed": {"C_A0": 0.1, "volumetric_flow_rate": 1.0},
            "stages": [
                {"type": "single", "reactor": {"type": "PFR", "volume": 2.0}}
            ],
        }
        out = run_catreactor("network", inp)
        # k*V/v0 = 1.0
        # Solve: -2*ln(1-XA) - XA = 1.0
        lo, hi = 0.0, 0.99
        for _ in range(200):
            mid = (lo + hi) / 2.0
            val = -2.0 * math.log(1.0 - mid) - mid
            if val < 1.0:
                lo = mid
            else:
                hi = mid
        xa_expected = (lo + hi) / 2.0
        ca_expected = 0.1 * (1.0 - xa_expected) / (1.0 + xa_expected)
        assert abs(out["outlet"]["X_A"] - xa_expected) < 1e-3
        assert abs(out["outlet"]["C_A"] - ca_expected) < 1e-3

    def test_cstr_gas_phase_second_order(self):
        """CSTR, 2nd order, gas phase with epsilon_A=1."""
        inp = {
            "kinetics": {"order": 2, "rate_constant": 10.0, "epsilon_A": 1.0},
            "feed": {"C_A0": 0.5, "volumetric_flow_rate": 1.0},
            "stages": [
                {"type": "single", "reactor": {"type": "CSTR", "volume": 5.0}}
            ],
        }
        out = run_catreactor("network", inp)
        # k*CA0*tau = 10*0.5*5 = 25
        target = 10.0 * 0.5 * 5.0
        lo, hi = 0.0, 0.999
        for _ in range(200):
            mid = (lo + hi) / 2.0
            val = mid * (1.0 + mid) ** 2 / (1.0 - mid) ** 2
            if val < target:
                lo = mid
            else:
                hi = mid
        xa_expected = (lo + hi) / 2.0
        ca_expected = 0.5 * (1.0 - xa_expected) / (1.0 + xa_expected)
        assert abs(out["outlet"]["X_A"] - xa_expected) < 1e-3
        assert abs(out["outlet"]["C_A"] - ca_expected) < 1e-3

    def test_cstr_gas_phase_first_order(self):
        """CSTR, 1st order, gas phase with epsilon_A=0.5."""
        inp = {
            "kinetics": {"order": 1, "rate_constant": 0.5, "epsilon_A": 0.5},
            "feed": {"C_A0": 0.2, "volumetric_flow_rate": 2.0},
            "stages": [
                {"type": "single", "reactor": {"type": "CSTR", "volume": 4.0}}
            ],
        }
        out = run_catreactor("network", inp)
        # k*tau = XA*(1+eps*XA)/(1-XA)
        # tau = V/v0 = 2, k*tau = 1
        # XA*(1+0.5*XA)/(1-XA) = 1
        # => 0.5*XA^2 + 2*XA - 1 = 0
        # XA = (-2 + sqrt(6)) / 1
        xa_expected = math.sqrt(6.0) - 2.0
        ca_expected = 0.2 * (1.0 - xa_expected) / (1.0 + 0.5 * xa_expected)
        assert abs(out["outlet"]["X_A"] - xa_expected) < 1e-3
        assert abs(out["outlet"]["C_A"] - ca_expected) < 1e-3


# ---------------------------------------------------------------------------
# SQLite Database Tests
# ---------------------------------------------------------------------------


class TestDBSchema:
    def test_schema_creates_valid_db_with_correct_data(self):
        """schema.sql must produce a database with correct adsorption constants."""
        db_path = "/tmp/test_schema_props.db"
        subprocess.run(["rm", "-f", db_path], check=False)
        try:
            with open("/app/schema.sql") as f:
                sql = f.read()
            result = subprocess.run(
                ["sqlite3", db_path],
                input=sql, capture_output=True, text=True,
            )
            assert result.returncode == 0, f"DB creation failed: {result.stderr}"

            # Species B: adsorption_K should be 2.5, NOT 38.0
            qr = subprocess.run(
                ["sqlite3", db_path,
                 "SELECT adsorption_K, heat_ads_kJ FROM species_properties WHERE name='B';"],
                capture_output=True, text=True,
            )
            vals = qr.stdout.strip().split("|")
            k_val = float(vals[0])
            h_val = float(vals[1])
            assert k_val < 5.0, (
                f"B.adsorption_K={k_val}, expected ~2.5 — "
                f"adsorption_K and heat_ads_kJ appear swapped"
            )
            assert h_val > 20.0, (
                f"B.heat_ads_kJ={h_val}, expected ~38.0"
            )

            # Species D: adsorption_K should be 1.2, NOT 30.0
            qr2 = subprocess.run(
                ["sqlite3", db_path,
                 "SELECT adsorption_K, heat_ads_kJ FROM species_properties WHERE name='D';"],
                capture_output=True, text=True,
            )
            vals2 = qr2.stdout.strip().split("|")
            k_val2 = float(vals2[0])
            h_val2 = float(vals2[1])
            assert k_val2 < 5.0, (
                f"D.adsorption_K={k_val2}, expected ~1.2 — "
                f"adsorption_K and heat_ads_kJ appear swapped"
            )
            assert h_val2 > 20.0, (
                f"D.heat_ads_kJ={h_val2}, expected ~30.0"
            )
        finally:
            subprocess.run(["rm", "-f", db_path], check=False)


class TestDBLookupRate:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        """Create the properties database from schema.sql before each test."""
        subprocess.run(["rm", "-f", "/app/properties.db"], check=False)
        with open("/app/schema.sql") as f:
            sql = f.read()
        result = subprocess.run(
            ["sqlite3", "/app/properties.db"],
            input=sql, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"DB init failed: {result.stderr}"
        yield
        subprocess.run(["rm", "-f", "/app/properties.db"], check=False)

    def test_lookup_unimolecular_rate(self):
        """Rate lookup for A -> M + N using species from the database."""
        inp = {
            "source": "database",
            "mechanism_type": "unimolecular",
            "reactants": ["A"],
            "k_sr": 0.1,
            "species_names": ["A", "M", "N"],
        }
        out = run_catreactor("rate", inp)
        # After fixing schema: A(K=2.0, C=0.5), M(K=0.5, C=0.1), N(K=0.3, C=0.05)
        denom = 1 + 2.0 * 0.5 + 0.5 * 0.1 + 0.3 * 0.05  # 2.065
        expected = 0.1 * 2.0 * 0.5 / (denom ** 2)
        assert abs(out["rate"] - expected) < 1e-4, (
            f"Expected rate={expected:.6f}, got {out['rate']:.6f}"
        )

    def test_lookup_bimolecular_rate(self):
        """Rate lookup for A + B -> C using species from the database."""
        inp = {
            "source": "database",
            "mechanism_type": "bimolecular",
            "reactants": ["A", "B"],
            "k_sr": 0.05,
            "species_names": ["A", "B"],
        }
        out = run_catreactor("rate", inp)
        # After fixing schema: A(K=2.0, C=0.5), B(K=2.5, C=0.4)
        denom = 1 + 2.0 * 0.5 + 2.5 * 0.4  # 3.0
        expected = 0.05 * 2.0 * 2.5 * 0.5 * 0.4 / (denom ** 2)
        assert abs(out["rate"] - expected) < 1e-4, (
            f"Expected rate={expected:.6f}, got {out['rate']:.6f}"
        )


# ---------------------------------------------------------------------------
# Batch Pipeline Tests (jq + shell)
# ---------------------------------------------------------------------------


class TestBatchPipeline:
    def test_batch_execution_produces_correct_rates(self):
        """batch_run.sh must process all cases and produce correct aggregated output."""
        out_path = "/tmp/batch_test_out.json"
        subprocess.run(["rm", "-f", out_path], check=False)
        try:
            result = subprocess.run(
                ["bash", "/app/batch_run.sh",
                 "/app/datasets/batch_cases.json", out_path],
                capture_output=True, text=True, timeout=60,
            )
            assert result.returncode == 0, (
                f"batch_run.sh failed:\nstdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
            assert os.path.exists(out_path), "Output file not created"

            with open(out_path) as f:
                results = json.load(f)

            assert isinstance(results, list), (
                f"Expected JSON array, got {type(results).__name__}"
            )
            assert len(results) == 2, f"Expected 2 results, got {len(results)}"

            # Case 0: unimolecular, A(K=2.0,C=0.5) + M(K=0.5,C=0.1)
            denom0 = 1 + 2.0 * 0.5 + 0.5 * 0.1  # 2.05
            exp0 = 0.1 * 2.0 * 0.5 / (denom0 ** 2)
            assert abs(results[0]["rate"] - exp0) < 1e-3, (
                f"Case 0: expected rate={exp0:.6f}, got {results[0]['rate']}"
            )

            # Case 1: bimolecular, A(K=1.5,C=0.3) + B(K=2.5,C=0.4)
            denom1 = 1 + 1.5 * 0.3 + 2.5 * 0.4  # 2.45
            exp1 = 0.05 * 1.5 * 2.5 * 0.3 * 0.4 / (denom1 ** 2)
            assert abs(results[1]["rate"] - exp1) < 1e-3, (
                f"Case 1: expected rate={exp1:.6f}, got {results[1]['rate']}"
            )
        finally:
            subprocess.run(["rm", "-f", out_path], check=False)


# ---------------------------------------------------------------------------
# Makefile Pipeline Tests
# ---------------------------------------------------------------------------


class TestMakePipeline:
    def test_make_init_creates_correct_db(self):
        """make init must create properties.db with valid species data."""
        subprocess.run(["rm", "-f", "/app/properties.db"], check=False)
        try:
            result = subprocess.run(
                ["make", "-C", "/app", "init"],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, (
                f"make init failed:\nstdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
            assert os.path.exists("/app/properties.db"), "properties.db not created"

            # Verify species A has correct adsorption_K
            qr = subprocess.run(
                ["sqlite3", "/app/properties.db",
                 "SELECT adsorption_K FROM species_properties WHERE name='A';"],
                capture_output=True, text=True,
            )
            val = float(qr.stdout.strip())
            assert abs(val - 2.0) < 0.01, (
                f"A.adsorption_K expected 2.0, got {val}"
            )
        finally:
            subprocess.run(["rm", "-f", "/app/properties.db"], check=False)

    def test_make_batch_runs_full_pipeline(self):
        """make batch must successfully run the batch processing pipeline."""
        subprocess.run(
            ["rm", "-f", "/app/datasets/batch_results.json"], check=False
        )
        try:
            result = subprocess.run(
                ["make", "-C", "/app", "batch"],
                capture_output=True, text=True, timeout=60,
            )
            assert result.returncode == 0, (
                f"make batch failed:\nstdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
            assert os.path.exists("/app/datasets/batch_results.json"), (
                "batch_results.json not created by make batch"
            )
        finally:
            subprocess.run(
                ["rm", "-f", "/app/datasets/batch_results.json"], check=False
            )

import pytest
import csv
import os
import subprocess



def read_results():
    """Read results.csv and return list of dicts with float values."""
    assert os.path.exists("/app/results.csv"), "results.csv not found"
    with open("/app/results.csv") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            rows.append({k: float(v) for k, v in r.items()})
    return rows


def read_benchmark():
    """Read benchmark.csv and return list of dicts."""
    assert os.path.exists("/app/benchmark.csv"), "benchmark.csv not found"
    with open("/app/benchmark.csv") as f:
        reader = csv.DictReader(f)
        return list(reader)


# ---------------------------------------------------------------------------
# 1. Compilation tests
# ---------------------------------------------------------------------------
class TestCompilation:
    def test_shared_library_exists(self):
        assert os.path.exists("/app/robertson_ext.so"), \
            "Compiled shared library robertson_ext.so not found in /app/"

    def test_derivs_symbol_exported(self):
        result = subprocess.run(
            ["nm", "-D", "/app/robertson_ext.so"],
            capture_output=True, text=True
        )
        assert "derivs" in result.stdout, \
            "robertson_ext.so does not export 'derivs' symbol"

    def test_jac_symbol_exported(self):
        """Analytical Jacobian must be implemented and exported."""
        result = subprocess.run(
            ["nm", "-D", "/app/robertson_ext.so"],
            capture_output=True, text=True
        )
        assert "jac" in result.stdout, \
            "robertson_ext.so does not export 'jac' symbol — " \
            "analytical Jacobian not implemented"


# ---------------------------------------------------------------------------
# 2. Results structure
# ---------------------------------------------------------------------------
class TestResultsStructure:
    def test_results_exist(self):
        rows = read_results()
        assert len(rows) > 0

    def test_required_columns(self):
        rows = read_results()
        for col in ["time", "y1", "y2", "y3", "y4"]:
            assert col in rows[0], f"Missing column: {col}"

    def test_output_times(self):
        rows = read_results()
        actual_times = [r["time"] for r in rows]
        expected = sorted([0, 0.4, 4, 40, 400, 500, 2000, 4000,
                           40000, 400000, 4000000, 40000000])
        assert len(actual_times) == len(expected), \
            f"Expected {len(expected)} time points, got {len(actual_times)}"
        for t_exp, t_act in zip(expected, actual_times):
            tol = max(1e-6, abs(t_exp) * 1e-8)
            assert abs(t_act - t_exp) < tol, \
                f"Time mismatch: expected {t_exp}, got {t_act}"


# ---------------------------------------------------------------------------
# 3. Initial conditions
# ---------------------------------------------------------------------------
class TestInitialConditions:
    def test_y1_initial(self):
        rows = read_results()
        assert abs(rows[0]["y1"] - 1.0) < 1e-6

    def test_y2_initial(self):
        rows = read_results()
        assert abs(rows[0]["y2"]) < 1e-6

    def test_y3_initial(self):
        rows = read_results()
        assert abs(rows[0]["y3"]) < 1e-6

    def test_y4_initial(self):
        rows = read_results()
        assert abs(rows[0]["y4"]) < 1e-6

    def test_time_initial(self):
        rows = read_results()
        assert abs(rows[0]["time"]) < 1e-10


# ---------------------------------------------------------------------------
# 4. Physical constraints
# ---------------------------------------------------------------------------
class TestPhysicalConstraints:
    def test_non_negativity(self):
        for row in read_results():
            for v in ["y1", "y2", "y3", "y4"]:
                assert row[v] >= -1e-10, \
                    f"{v}={row[v]} negative at t={row['time']}"

    def test_y2_remains_small(self):
        """y2 is a fast intermediate and must remain very small."""
        for row in read_results():
            if row["time"] > 1.0:
                assert row["y2"] < 0.01, \
                    f"y2={row['y2']} too large at t={row['time']}"


# ---------------------------------------------------------------------------
# 5. Mass conservation (sum = y1+y2+y3+y4 = const between events)
#
#    deSolve outputs pre-event state at event output times:
#    - At t=500 output is the state BEFORE the 0.2 injection → sum ≈ 1.0
#    - At t=2000 the first injection has been integrated but the second
#      has not yet fired → sum ≈ 1.2
#    - After t=2000, both injections are applied → sum ≈ 1.5
# ---------------------------------------------------------------------------
class TestMassConservation:
    def _total(self, row):
        return row["y1"] + row["y2"] + row["y3"] + row["y4"]

    def test_pre_event_mass(self):
        for row in read_results():
            if row["time"] <= 500 + 1e-6:
                total = self._total(row)
                assert abs(total - 1.0) < 1e-4, \
                    f"Mass violated at t={row['time']}: sum={total}, expected 1.0"

    def test_inter_event_mass(self):
        rows = read_results()
        for r in rows:
            if abs(r["time"] - 2000) < 1e-6:
                total = self._total(r)
                assert abs(total - 1.2) < 1e-4, \
                    f"At t=2000: sum={total}, expected 1.2 (post-first-event)"
                return
        pytest.fail("No output at t=2000")

    def test_post_event_mass(self):
        count = 0
        for row in read_results():
            if row["time"] > 2000 + 1e-6:
                total = self._total(row)
                assert abs(total - 1.5) < 1e-4, \
                    f"Mass violated at t={row['time']}: sum={total}, expected 1.5"
                count += 1
        assert count > 0, "No output points found after t=2000"

    def test_event_mass_jump(self):
        rows = read_results()
        mass_500 = None
        mass_2000 = None
        for r in rows:
            if abs(r["time"] - 500) < 1e-6:
                mass_500 = self._total(r)
            if abs(r["time"] - 2000) < 1e-6:
                mass_2000 = self._total(r)
        assert mass_500 is not None and mass_2000 is not None
        jump = mass_2000 - mass_500
        assert abs(jump - 0.2) < 1e-3, \
            f"Mass jump from t=500 to t=2000 should be ~0.2, got {jump}"


# ---------------------------------------------------------------------------
# 6. Qualitative behaviour
# ---------------------------------------------------------------------------
class TestQualitativeBehavior:
    def test_y1_decreases_overall(self):
        rows = read_results()
        assert rows[-1]["y1"] < rows[0]["y1"]

    def test_y4_increases_overall(self):
        rows = read_results()
        assert rows[-1]["y4"] > rows[0]["y4"]

    def test_y4_dominant_at_late_time(self):
        """At t=4e7, nearly all mass has flowed through to the terminal
        product y4 (k4 timescale ≈ 1000 ≪ 4e7)."""
        rows = read_results()
        last = rows[-1]
        assert last["y4"] > 1.0, \
            f"y4={last['y4']} at final time should exceed 1.0"

    def test_y3_present_at_intermediate_time(self):
        """y3 should have accumulated visibly by t=4000."""
        rows = read_results()
        for r in rows:
            if abs(r["time"] - 4000) < 1e-6:
                assert r["y3"] > 0.01, \
                    f"y3={r['y3']} at t=4000 should be > 0.01"
                return
        pytest.fail("No output at t=4000")

    def test_early_solution_reasonable(self):
        """At t=0.4, f(t)≈1.0 and the system has barely evolved."""
        rows = read_results()
        for r in rows:
            if abs(r["time"] - 0.4) < 1e-6:
                assert 0.95 < r["y1"] < 1.0, \
                    f"y1 at t=0.4 should be near 0.985, got {r['y1']}"
                return
        pytest.fail("No output at t=0.4")


# ---------------------------------------------------------------------------
# 7. Forcing effect
# ---------------------------------------------------------------------------
class TestForcingEffect:
    def test_forcing_accelerates_reaction(self):
        """The forcing data ramps from 1.0 to 2.0. Without forcing
        (constant f=1), y1(400) ≈ 0.45. With active forcing (average
        f ≈ 1.2 over [0,400]), y1 should be noticeably lower."""
        rows = read_results()
        for r in rows:
            if abs(r["time"] - 400) < 1e-6:
                assert r["y1"] < 0.44, \
                    f"y1 at t=400 should be < 0.44 with active forcing, " \
                    f"got {r['y1']}. Value near 0.45 suggests forcing " \
                    f"data is not influencing the dynamics."
                return
        pytest.fail("No output at t=400")


# ---------------------------------------------------------------------------
# 8. Solver benchmark
# ---------------------------------------------------------------------------
class TestBenchmark:
    def test_benchmark_exists(self):
        assert os.path.exists("/app/benchmark.csv"), \
            "benchmark.csv not found — solver comparison was not performed"

    def test_benchmark_columns(self):
        rows = read_benchmark()
        assert len(rows) > 0, "benchmark.csv is empty"
        for col in ["solver", "nsteps", "nfevls", "njevls"]:
            assert col in rows[0], \
                f"benchmark.csv missing required column: {col}"

    def test_benchmark_min_configs(self):
        """At least 3 distinct solver configurations must be benchmarked."""
        rows = read_benchmark()
        assert len(rows) >= 3, \
            f"Expected ≥3 solver configurations, got {len(rows)}"

    def test_benchmark_values_vary(self):
        """Different configurations should produce different function
        evaluation counts, confirming they are genuinely distinct."""
        rows = read_benchmark()
        nfevls_values = set()
        for r in rows:
            try:
                nfevls_values.add(int(float(r["nfevls"])))
            except (ValueError, KeyError):
                pass
        assert len(nfevls_values) >= 2, \
            "All solver configurations report identical nfevls — " \
            "benchmark may not reflect genuinely different strategies"

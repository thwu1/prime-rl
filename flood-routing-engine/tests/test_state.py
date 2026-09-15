"""
Verification tests for the flood routing simulator.
Tests correctness of channel routing and reservoir routing computations.
"""

import subprocess
import os
import csv
import math
import pytest


# ============================================================
# Reference implementation for independent verification
# ============================================================

def generate_hydrograph(dt, duration, baseflow, peak_flow, rise_time, fall_time):
    n = int(duration / dt) + 1
    Q = []
    for i in range(n):
        t = i * dt
        if t <= rise_time:
            Q.append(baseflow + (peak_flow - baseflow) * t / rise_time)
        elif t <= rise_time + fall_time:
            Q.append(peak_flow - (peak_flow - baseflow) * (t - rise_time) / fall_time)
        else:
            Q.append(baseflow)
    return Q


def _trap_area(b, z, y):
    return (b + z * y) * y


def _trap_perimeter(b, z, y):
    return b + 2.0 * y * math.sqrt(1.0 + z * z)


def _trap_top_width(b, z, y):
    return b + 2.0 * z * y


def _mannings_Q(b, z, n, S, y):
    if y <= 0:
        return 0.0
    A = _trap_area(b, z, y)
    P = _trap_perimeter(b, z, y)
    if P < 1e-12:
        return 0.0
    R = A / P
    return (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(S)


def _normal_depth(b, z, n, S, Q):
    if Q <= 0:
        return 0.0
    lo, hi = 0.0, 50.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _mannings_Q(b, z, n, S, mid) < Q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _wave_celerity(b, z, n, S, Q):
    if Q <= 0:
        return 0.01
    y = _normal_depth(b, z, n, S, Q)
    if y < 1e-8:
        return 0.01
    dy = max(y * 0.001, 1e-6)
    Q1 = _mannings_Q(b, z, n, S, y)
    Q2 = _mannings_Q(b, z, n, S, y + dy)
    A1 = _trap_area(b, z, y)
    A2 = _trap_area(b, z, y + dy)
    dA = A2 - A1
    if abs(dA) < 1e-15:
        return 0.01
    c = (Q2 - Q1) / dA
    return max(c, 0.01)


def ref_muskingum_cunge(inflow, dt, b, z, n, S0, L):
    """Reference variable-coefficient channel routing."""
    num = len(inflow)
    Q_peak = max(inflow)
    Q_base = inflow[0]
    Q_ref = Q_base + 0.5 * (Q_peak - Q_base)
    c_ref = _wave_celerity(b, z, n, S0, Q_ref)

    dx = c_ref * dt
    num_sub = max(1, round(L / dx))
    dx = L / num_sub

    cur = list(inflow)
    for _ in range(num_sub):
        out = [cur[0]]
        for t in range(1, num):
            Q_avg = max((cur[t] + cur[t - 1] + out[t - 1]) / 3.0, 0.01)
            y_avg = _normal_depth(b, z, n, S0, Q_avg)
            B = _trap_top_width(b, z, y_avg)
            c = max(_wave_celerity(b, z, n, S0, Q_avg), 0.01)
            K = dx / c
            X = 0.5 * (1.0 - Q_avg / (B * S0 * c * dx))
            X = max(0.0, min(0.5, X))
            r = dt / K
            denom = r + 2.0 * (1.0 - X)
            C1 = (r + 2.0 * X) / denom
            C2 = (r - 2.0 * X) / denom
            C3 = (2.0 * (1.0 - X) - r) / denom
            O = C1 * cur[t - 1] + C2 * cur[t] + C3 * out[t - 1]
            out.append(max(O, 0.0))
        cur = out
    return cur


def _interp(table, x, xcol, ycol):
    """Linear interpolation on a list of tuples."""
    if x <= table[0][xcol]:
        return table[0][ycol]
    if x >= table[-1][xcol]:
        return table[-1][ycol]
    for i in range(1, len(table)):
        if x <= table[i][xcol]:
            frac = (x - table[i - 1][xcol]) / (table[i][xcol] - table[i - 1][xcol])
            return table[i - 1][ycol] + frac * (table[i][ycol] - table[i - 1][ycol])
    return table[-1][ycol]


def ref_modified_puls(inflow, dt, so_table):
    """Reference level-pool reservoir routing.
    so_table: list of (storage_m3, outflow_m3s) tuples.
    """
    num = len(inflow)
    outflow = [inflow[0]]
    S_prev = _interp(so_table, outflow[0], 1, 0)

    for t in range(1, num):
        rhs = (inflow[t - 1] + inflow[t]) / 2.0 + S_prev / dt - outflow[t - 1] / 2.0
        # Bisection: find O such that S(O)/dt + O/2 = rhs
        O_lo, O_hi = 0.0, so_table[-1][1] * 2.0
        for _ in range(100):
            O_mid = (O_lo + O_hi) / 2.0
            S_mid = _interp(so_table, O_mid, 1, 0)
            lhs = S_mid / dt + O_mid / 2.0
            if lhs < rhs:
                O_lo = O_mid
            else:
                O_hi = O_mid
        O_t = max((O_lo + O_hi) / 2.0, 0.0)
        outflow.append(O_t)
        S_prev = _interp(so_table, O_t, 1, 0)
    return outflow


# ============================================================
# Test helpers
# ============================================================

BINARY_PATH = '/app/build/flood_router'


def build():
    r = subprocess.run(
        ['cmake', '-B', '/app/build', '-S', '/app'],
        capture_output=True, text=True
    )
    assert r.returncode == 0, f"CMake configure failed:\n{r.stderr}"
    r = subprocess.run(
        ['cmake', '--build', '/app/build'],
        capture_output=True, text=True
    )
    assert r.returncode == 0, f"Build failed:\n{r.stderr}"
    assert os.path.exists(BINARY_PATH), (
        f"Binary not found at {BINARY_PATH}. "
        "Check that the CMake target name is 'flood_router'."
    )


def run_router(scenario_path, output_path):
    r = subprocess.run(
        [BINARY_PATH, scenario_path, output_path],
        capture_output=True, text=True, cwd='/app', timeout=120
    )
    assert r.returncode == 0, f"Router failed (exit {r.returncode}):\n{r.stderr}"


def read_csv_output(path):
    times, flows = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row['time_s']))
            flows.append(float(row['flow_m3s']))
    return times, flows


def calc_nrmse(actual, expected, norm):
    """Normalized root-mean-square error."""
    n = min(len(actual), len(expected))
    sse = sum((actual[i] - expected[i]) ** 2 for i in range(n))
    return math.sqrt(sse / n) / norm


def write_scenario(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# Shared scenario definitions
REACH_ONLY_SCENARIO = """\
TIMESTEP 300
TOTAL_DURATION 108000
HYDROGRAPH
BASEFLOW 5.0
PEAK_FLOW 80.0
RISE_TIME 21600
FALL_TIME 64800
END
REACH reach1
LENGTH 10000.0
SLOPE 0.001
MANNING_N 0.035
BOTTOM_WIDTH 10.0
SIDE_SLOPE 2.0
END
ROUTE reach1
"""

RESERVOIR_ONLY_SCENARIO = """\
TIMESTEP 300
TOTAL_DURATION 108000
HYDROGRAPH
BASEFLOW 5.0
PEAK_FLOW 80.0
RISE_TIME 21600
FALL_TIME 64800
END
RESERVOIR res1
STORAGE_OUTFLOW
0 0
50000 2
150000 8
300000 20
500000 40
800000 70
1200000 110
1800000 170
END
ROUTE res1
"""

SO_TABLE = [
    (0, 0), (50000, 2), (150000, 8), (300000, 20),
    (500000, 40), (800000, 70), (1200000, 110), (1800000, 170),
]

INFLOW_KW = dict(dt=300, duration=108000, baseflow=5.0,
                 peak_flow=80.0, rise_time=21600, fall_time=64800)


# ============================================================
# Tests
# ============================================================

class TestBuildAndRun:
    def test_cmake_configures(self):
        r = subprocess.run(
            ['cmake', '-B', '/app/build', '-S', '/app'],
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"CMake configure failed:\n{r.stderr}"

    def test_compiles(self):
        build()

    def test_binary_exists(self):
        build()
        assert os.path.exists(BINARY_PATH), (
            f"Expected binary at {BINARY_PATH}"
        )

    def test_runs_without_crash(self):
        build()
        run_router('/app/data/scenario.txt', '/tmp/tb_run.csv')
        assert os.path.exists('/tmp/tb_run.csv')

    def test_output_format(self):
        build()
        run_router('/app/data/scenario.txt', '/tmp/tb_fmt.csv')
        times, flows = read_csv_output('/tmp/tb_fmt.csv')
        assert len(times) > 100, "Too few output rows"
        assert len(times) == len(flows)
        assert times[0] == 0.0
        assert abs(times[1] - times[0] - 300.0) < 0.01


class TestOutputQuality:
    @pytest.fixture(autouse=True)
    def _setup(self):
        build()
        run_router('/app/data/scenario.txt', '/tmp/tb_qual.csv')
        self.times, self.flows = read_csv_output('/tmp/tb_qual.csv')
        self.inflow = generate_hydrograph(**INFLOW_KW)

    def test_no_invalid_values(self):
        for i, f in enumerate(self.flows):
            assert not math.isnan(f), f"NaN at timestep {i}"
            assert not math.isinf(f), f"Inf at timestep {i}"
            assert f >= 0, f"Negative flow {f:.4f} at timestep {i}"

    def test_peak_attenuated(self):
        out_peak = max(self.flows)
        in_peak = max(self.inflow)
        assert out_peak < in_peak * 0.90, (
            f"Peak not attenuated enough: output {out_peak:.2f} vs input {in_peak:.2f}"
        )

    def test_peak_delayed(self):
        in_peak_idx = self.inflow.index(max(self.inflow))
        out_peak_idx = self.flows.index(max(self.flows))
        assert out_peak_idx > in_peak_idx, (
            f"Peak not delayed: input peak at {in_peak_idx}, output at {out_peak_idx}"
        )

    def test_smoothness(self):
        peak = max(self.flows)
        for i in range(1, len(self.flows)):
            jump = abs(self.flows[i] - self.flows[i - 1])
            assert jump < 0.20 * peak, (
                f"Oscillation at step {i}: jump={jump:.4f}, peak={peak:.4f}"
            )


class TestAccuracy:
    @pytest.fixture(autouse=True)
    def _setup(self):
        build()
        self.inflow = generate_hydrograph(**INFLOW_KW)

    def test_single_reach_accuracy(self):
        write_scenario('/tmp/sc_reach.txt', REACH_ONLY_SCENARIO)
        run_router('/tmp/sc_reach.txt', '/tmp/out_reach.csv')
        _, flows = read_csv_output('/tmp/out_reach.csv')
        ref = ref_muskingum_cunge(
            self.inflow, 300, 10.0, 2.0, 0.035, 0.001, 10000.0
        )
        err = calc_nrmse(flows, ref, max(self.inflow))
        assert err < 0.05, f"Single reach NRMSE = {err:.4f} (limit 0.05)"

    def test_reservoir_accuracy(self):
        write_scenario('/tmp/sc_res.txt', RESERVOIR_ONLY_SCENARIO)
        run_router('/tmp/sc_res.txt', '/tmp/out_res.csv')
        _, flows = read_csv_output('/tmp/out_res.csv')
        ref = ref_modified_puls(self.inflow, 300, SO_TABLE)
        err = calc_nrmse(flows, ref, max(self.inflow))
        assert err < 0.05, f"Reservoir NRMSE = {err:.4f} (limit 0.05)"

    def test_full_network_accuracy(self):
        run_router('/app/data/scenario.txt', '/tmp/out_full.csv')
        _, flows = read_csv_output('/tmp/out_full.csv')
        # Reference: reach1 -> reservoir -> reach2
        f = ref_muskingum_cunge(
            self.inflow, 300, 10.0, 2.0, 0.035, 0.001, 10000.0
        )
        f = ref_modified_puls(f, 300, SO_TABLE)
        f = ref_muskingum_cunge(
            f, 300, 15.0, 3.0, 0.040, 0.0005, 15000.0
        )
        err = calc_nrmse(flows, f, max(self.inflow))
        assert err < 0.05, f"Full network NRMSE = {err:.4f} (limit 0.05)"

    def test_mass_balance_single_reach(self):
        write_scenario('/tmp/sc_mb.txt', REACH_ONLY_SCENARIO)
        run_router('/tmp/sc_mb.txt', '/tmp/out_mb.csv')
        _, flows = read_csv_output('/tmp/out_mb.csv')
        dt = 300
        vol_in = sum(self.inflow) * dt
        vol_out = sum(flows) * dt
        rel_err = abs(vol_in - vol_out) / vol_in
        assert rel_err < 0.02, f"Mass balance error = {rel_err:.4f} (limit 0.02)"

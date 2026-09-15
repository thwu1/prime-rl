
import os
import re
import csv
import subprocess
import pytest


def run_ngspice(netlist_path, timeout=180):
    """Run ngspice in batch mode and return combined stdout+stderr."""
    result = subprocess.run(
        ['ngspice', '-b', netlist_path],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout + '\n' + result.stderr


def parse_meas_value(output, name):
    """Parse a named measurement from ngspice output."""
    match = re.search(
        rf'{name}\s*=\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)',
        output, re.IGNORECASE
    )
    if not match:
        return None
    return float(match.group(1))


REQUIRED_LOADS = [30, 60, 120, 240, 600]


# ---------------------------------------------------------------------------
# Test class: Dead-time sweep
# ---------------------------------------------------------------------------
class TestDeadtimeSweep:
    """Verify the dead-time optimization sweep was performed correctly."""

    @pytest.fixture(scope='class')
    def sweep_data(self):
        with open('/app/results/deadtime_sweep.csv') as f:
            reader = csv.DictReader(f)
            return list(reader)

    def test_sweep_file_exists(self):
        assert os.path.isfile('/app/results/deadtime_sweep.csv'), \
            "Missing /app/results/deadtime_sweep.csv"

    def test_sweep_has_enough_rows(self, sweep_data):
        assert len(sweep_data) >= 5, \
            f"Dead-time sweep has {len(sweep_data)} rows, need >= 5"

    def test_sweep_has_required_columns(self, sweep_data):
        for col in ['dead_time_ns', 'efficiency_pct']:
            assert col in sweep_data[0], f"Missing column '{col}' in sweep CSV"

    def test_sweep_deadtimes_distinct(self, sweep_data):
        dts = set(float(row['dead_time_ns']) for row in sweep_data)
        assert len(dts) >= 5, \
            f"Need >= 5 distinct dead-time values, got {len(dts)}"

    def test_sweep_deadtimes_in_range(self, sweep_data):
        for row in sweep_data:
            dt = float(row['dead_time_ns'])
            assert 5 <= dt <= 300, \
                f"Dead-time {dt} ns outside acceptable [5, 300] range"

    def test_sweep_efficiencies_reasonable(self, sweep_data):
        for row in sweep_data:
            eff = float(row['efficiency_pct'])
            assert eff == 0 or (30.0 <= eff <= 99.9), \
                f"Efficiency {eff}% unreasonable at dt={row['dead_time_ns']} ns"


# ---------------------------------------------------------------------------
# Test class: Optimal dead-time self-consistency
# ---------------------------------------------------------------------------
class TestOptimalDeadtime:
    """Verify optimal dead-time is self-consistent with sweep data."""

    def test_optimal_file_exists(self):
        assert os.path.isfile('/app/results/optimal_deadtime_ns.txt'), \
            "Missing /app/results/optimal_deadtime_ns.txt"

    def test_optimal_is_positive(self):
        with open('/app/results/optimal_deadtime_ns.txt') as f:
            val = float(f.read().strip())
        assert val > 0, f"Optimal dead-time must be positive, got {val}"

    def test_optimal_matches_best_in_sweep(self):
        """The chosen dead-time must correspond to the highest efficiency."""
        with open('/app/results/optimal_deadtime_ns.txt') as f:
            optimal = float(f.read().strip())

        with open('/app/results/deadtime_sweep.csv') as f:
            sweep = list(csv.DictReader(f))

        max_eff = max(float(r['efficiency_pct']) for r in sweep)
        best_dts = [
            float(r['dead_time_ns']) for r in sweep
            if abs(float(r['efficiency_pct']) - max_eff) < 0.05
        ]

        assert any(abs(optimal - dt) < 1.0 for dt in best_dts), \
            f"Optimal {optimal} ns doesn't match any best-efficiency " \
            f"entry in sweep: {best_dts}"


# ---------------------------------------------------------------------------
# Test class: Efficiency map (multi-load comparison)
# ---------------------------------------------------------------------------
class TestEfficiencyMap:
    """Verify the multi-load efficiency evaluation was performed."""

    @pytest.fixture(scope='class')
    def map_data(self):
        with open('/app/results/efficiency_map.csv') as f:
            return list(csv.DictReader(f))

    def test_map_file_exists(self):
        assert os.path.isfile('/app/results/efficiency_map.csv'), \
            "Missing /app/results/efficiency_map.csv"

    def test_map_has_required_columns(self, map_data):
        for col in ['load_ohms', 'async_eff_pct', 'sync_eff_pct']:
            assert col in map_data[0], f"Missing column '{col}' in map CSV"

    def test_map_has_five_rows(self, map_data):
        assert len(map_data) == 5, \
            f"Efficiency map has {len(map_data)} rows, expected 5"

    def test_map_has_correct_load_points(self, map_data):
        loads = sorted(int(float(r['load_ohms'])) for r in map_data)
        assert loads == REQUIRED_LOADS, \
            f"Expected load points {REQUIRED_LOADS}, got {loads}"

    def test_map_async_efficiencies_reasonable(self, map_data):
        """Async efficiency can drop significantly at light loads due to
        Schottky diode forward voltage dominating in DCM operation with
        fixed open-loop duty cycle."""
        for row in map_data:
            eff = float(row['async_eff_pct'])
            assert 10.0 <= eff <= 99.5, \
                f"Async efficiency {eff}% unreasonable at {row['load_ohms']} ohm"

    def test_map_sync_efficiencies_reasonable(self, map_data):
        """Sync efficiency can exceed 99% at light loads because MOSFET
        channel I^2*Rds_on losses become negligible at low currents in
        simulation models without detailed gate-drive loss modeling."""
        for row in map_data:
            eff = float(row['sync_eff_pct'])
            assert 30.0 <= eff <= 99.9, \
                f"Sync efficiency {eff}% unreasonable at {row['load_ohms']} ohm"


# ---------------------------------------------------------------------------
# Test class: Topology report format and consistency
# ---------------------------------------------------------------------------
class TestTopologyReport:
    """Verify the topology recommendation is well-formed and consistent
    with the measured efficiency data."""

    @pytest.fixture(scope='class')
    def report_lines(self):
        with open('/app/results/topology_report.txt') as f:
            return [line.rstrip('\n') for line in f.readlines()]

    @pytest.fixture(scope='class')
    def map_data(self):
        with open('/app/results/efficiency_map.csv') as f:
            return list(csv.DictReader(f))

    def test_report_file_exists(self):
        assert os.path.isfile('/app/results/topology_report.txt'), \
            "Missing /app/results/topology_report.txt"

    def test_report_has_enough_lines(self, report_lines):
        assert len(report_lines) >= 5, \
            f"topology_report.txt has {len(report_lines)} lines, need >= 5"

    def test_report_valid_recommendation(self, report_lines):
        rec = report_lines[0].strip().lower()
        assert rec in ('async', 'sync', 'load-dependent'), \
            f"Line 1 must be async/sync/load-dependent, got '{rec}'"

    def test_report_crossover_valid(self, report_lines):
        rec = report_lines[0].strip().lower()
        crossover = report_lines[1].strip()
        if rec == 'load-dependent':
            val = float(crossover)
            assert 20 <= val <= 700, \
                f"Crossover {val} ohm outside [20, 700] range"
        else:
            assert crossover.upper() == 'N/A', \
                f"Non-load-dependent recommendation should have N/A crossover"

    def test_report_recommendation_consistent_with_map(self, report_lines,
                                                        map_data):
        """Recommendation must be consistent with efficiency data."""
        rec = report_lines[0].strip().lower()

        async_better = sum(
            1 for r in map_data
            if float(r['async_eff_pct']) > float(r['sync_eff_pct']) + 0.5
        )
        sync_better = sum(
            1 for r in map_data
            if float(r['sync_eff_pct']) > float(r['async_eff_pct']) + 0.5
        )

        if rec == 'load-dependent':
            assert async_better >= 1 and sync_better >= 1, \
                f"'load-dependent' but async wins {async_better}, " \
                f"sync wins {sync_better} load points"
        elif rec == 'sync':
            assert sync_better >= async_better, \
                f"Recommended 'sync' but async wins more points " \
                f"({async_better} vs {sync_better})"
        elif rec == 'async':
            assert async_better >= sync_better, \
                f"Recommended 'async' but sync wins more points " \
                f"({sync_better} vs {async_better})"

    def test_report_light_load_analysis_substantive(self, report_lines):
        line3 = report_lines[2].strip()
        assert len(line3) >= 40, \
            f"Light-load analysis too short ({len(line3)} chars)"

    def test_report_heavy_load_analysis_substantive(self, report_lines):
        line4 = report_lines[3].strip()
        assert len(line4) >= 40, \
            f"Heavy-load analysis too short ({len(line4)} chars)"

    def test_report_recommendation_has_quantitative_support(self,
                                                             report_lines):
        """Final recommendation must reference numeric efficiency values."""
        body = ' '.join(report_lines[4:])
        numbers = re.findall(r'\d+\.\d+', body)
        assert len(numbers) >= 2, \
            "Final recommendation must reference at least 2 numeric " \
            "efficiency values from the evaluation"


# ---------------------------------------------------------------------------
# Test class: Netlist integrity
# ---------------------------------------------------------------------------
class TestNetlistIntegrity:
    """Verify both netlists were properly fixed for ngspice."""

    def test_async_no_level7(self):
        with open('/app/async_boost.cir') as f:
            content = f.read()
        assert 'LEVEL=7' not in content.upper(), \
            "async_boost.cir still contains PSPICE LEVEL=7"

    def test_sync_no_level7(self):
        with open('/app/sync_boost.cir') as f:
            content = f.read()
        assert 'LEVEL=7' not in content.upper(), \
            "sync_boost.cir still contains PSPICE LEVEL=7"

    def test_async_has_convergence_options(self):
        with open('/app/async_boost.cir') as f:
            content = f.read().lower()
        assert '.options' in content or '.option' in content, \
            "async_boost.cir missing convergence .options directive"

    def test_sync_has_convergence_options(self):
        with open('/app/sync_boost.cir') as f:
            content = f.read().lower()
        assert '.options' in content or '.option' in content, \
            "sync_boost.cir missing convergence .options directive"

    def test_sync_nonzero_deadtime(self):
        with open('/app/sync_boost.cir') as f:
            content = f.read()
        match = re.search(r'dead_time\s*=\s*(\S+)', content, re.IGNORECASE)
        assert match, "dead_time parameter not found in sync_boost.cir"
        val_str = match.group(1).strip()
        assert val_str != '0' and val_str != '0.0', \
            "sync_boost.cir dead_time must not be zero (causes shoot-through)"


# ---------------------------------------------------------------------------
# Test class: Anti-cheat — re-run simulations and compare
# ---------------------------------------------------------------------------
class TestAntiCheat:
    """Re-run both simulations at 60 ohm to verify results were not
    fabricated. Netlists should be left at 60 ohm after evaluation."""

    @pytest.fixture(scope='class')
    def async_sim_output(self):
        return run_ngspice('/app/async_boost.cir')

    @pytest.fixture(scope='class')
    def sync_sim_output(self):
        return run_ngspice('/app/sync_boost.cir')

    @pytest.fixture(scope='class')
    def map_60(self):
        with open('/app/results/efficiency_map.csv') as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if int(float(r['load_ohms'])) == 60:
                return r
        pytest.fail("No 60 ohm row in efficiency_map.csv")

    def test_async_simulates_successfully(self, async_sim_output):
        val = parse_meas_value(async_sim_output, 'vout_avg')
        assert val is not None, \
            "async_boost.cir failed to produce vout_avg measurement. " \
            f"Output tail: {async_sim_output[-500:]}"

    def test_async_efficiency_matches_map(self, async_sim_output, map_60):
        vout = abs(parse_meas_value(async_sim_output, 'vout_avg'))
        iin = parse_meas_value(async_sim_output, 'iin_avg')
        assert iin is not None, "iin_avg not found in async simulation output"
        pin = -5.0 * iin
        pout = vout * vout / 60.0
        sim_eff = 100.0 * pout / pin if pin > 0 else 0.0
        stored_eff = float(map_60['async_eff_pct'])
        assert abs(sim_eff - stored_eff) < 3.0, \
            f"Async 60 ohm: re-simulated eff {sim_eff:.1f}% vs " \
            f"stored {stored_eff:.1f}% (diff > 3 pp)"

    def test_sync_simulates_successfully(self, sync_sim_output):
        val = parse_meas_value(sync_sim_output, 'vout_avg')
        assert val is not None, \
            "sync_boost.cir failed to produce vout_avg measurement. " \
            f"Output tail: {sync_sim_output[-500:]}"

    def test_sync_efficiency_matches_map(self, sync_sim_output, map_60):
        vout = abs(parse_meas_value(sync_sim_output, 'vout_avg'))
        iin = parse_meas_value(sync_sim_output, 'iin_avg')
        assert iin is not None, "iin_avg not found in sync simulation output"
        pin = -5.0 * iin
        pout = vout * vout / 60.0
        sim_eff = 100.0 * pout / pin if pin > 0 else 0.0
        stored_eff = float(map_60['sync_eff_pct'])
        assert abs(sim_eff - stored_eff) < 3.0, \
            f"Sync 60 ohm: re-simulated eff {sim_eff:.1f}% vs " \
            f"stored {stored_eff:.1f}% (diff > 3 pp)"

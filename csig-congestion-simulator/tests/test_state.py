"""
Tests for CSIG Multi-Bottleneck Fairness Analysis.

Verifies both CSIG-AIMD simulation and progressive filling analytical solver
produce correct weighted max-min fair rates for a datacenter topology with
4 bottleneck groups connected by high-capacity backplane links.

"""
import csv
import json
import os
import shutil
import subprocess

import pytest

# Analytical weighted max-min fair rates via progressive filling.
# Topology: 7 links (4 bottleneck + 3 connector), 10 weighted flows.
# Progressive filling order: L2(10/w) -> L0(15/w) -> L1(20/w) -> L6(30/w)
#
# Step 1: L2 saturates (cap=30, F6(w=1)+F7(w=2), total_w=3) -> F6=10, F7=20
# Step 2: L0 saturates (cap=60, F0(w=1)+F1(w=2)+F2(w=1), total_w=4) -> F0=15, F1=30, F2=15
# Step 3: L1 saturates (cap=100, F3(w=1)+F4(w=2)+F5(w=2), total_w=5) -> F3=20, F4=40, F5=40
# Step 4: L6 saturates (cap=90, F8(w=1)+F9(w=2), total_w=3) -> F8=30, F9=60
EXPECTED_ANALYTICAL = {
    "F0": 15.0,
    "F1": 30.0,
    "F2": 15.0,
    "F3": 20.0,
    "F4": 40.0,
    "F5": 40.0,
    "F6": 10.0,
    "F7": 20.0,
    "F8": 30.0,
    "F9": 60.0,
}

EXPECTED_BOTTLENECKS = {
    "F0": "L0", "F1": "L0", "F2": "L0",
    "F3": "L1", "F4": "L1", "F5": "L1",
    "F6": "L2", "F7": "L2",
    "F8": "L6", "F9": "L6",
}

EXPECTED_FILLING_ORDER = ["L2", "L0", "L1", "L6"]

SATURATED_LINKS = ["L0", "L1", "L2", "L6"]
CONNECTOR_LINKS = ["L3", "L4", "L5"]

SIM_TOLERANCE = 0.08
ANA_TOLERANCE = 0.005


class TestOutputFilesExist:
    def test_simulation_rates(self):
        assert os.path.exists("/app/output/simulation_rates.json"), \
            "Missing /app/output/simulation_rates.json"

    def test_analytical_rates(self):
        assert os.path.exists("/app/output/analytical_rates.json"), \
            "Missing /app/output/analytical_rates.json"

    def test_link_utilization(self):
        assert os.path.exists("/app/output/link_utilization.json"), \
            "Missing /app/output/link_utilization.json"

    def test_summary(self):
        assert os.path.exists("/app/output/summary.json"), \
            "Missing /app/output/summary.json"

    def test_comparison(self):
        assert os.path.exists("/app/output/comparison.json"), \
            "Missing /app/output/comparison.json"

    def test_convergence_dat(self):
        assert os.path.exists("/app/output/convergence.dat"), \
            "Missing /app/output/convergence.dat"

    def test_convergence_png(self):
        assert os.path.exists("/app/output/convergence.png"), \
            "Missing /app/output/convergence.png"
        assert os.path.getsize("/app/output/convergence.png") > 100, \
            "convergence.png appears empty or corrupt"


class TestJsonValidity:
    """Verify all JSON output passes jq validation."""

    @pytest.mark.parametrize("fname", [
        "simulation_rates.json", "analytical_rates.json",
        "link_utilization.json", "summary.json", "comparison.json",
    ])
    def test_jq_valid(self, fname):
        result = subprocess.run(
            ["jq", ".", f"/app/output/{fname}"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"{fname} fails jq validation: {result.stderr}"


class TestAnalyticalRates:
    """Verify progressive filling produces exact weighted max-min fair rates."""

    @pytest.fixture(autouse=True)
    def load(self):
        with open("/app/output/analytical_rates.json") as f:
            self.rates = json.load(f)

    def test_all_flows_present(self):
        for fid in EXPECTED_ANALYTICAL:
            assert fid in self.rates, f"Missing flow {fid} in analytical_rates.json"

    @pytest.mark.parametrize("fid,expected", list(EXPECTED_ANALYTICAL.items()))
    def test_rate_accuracy(self, fid, expected):
        actual = self.rates[fid]
        rel = abs(actual - expected) / expected
        assert rel < ANA_TOLERANCE, (
            f"Analytical {fid}: expected ~{expected:.4f}, got {actual:.4f} "
            f"(error {rel:.4%}, tolerance {ANA_TOLERANCE:.1%})"
        )


class TestSimulationRates:
    """Verify CSIG-AIMD simulation converges near expected allocation."""

    @pytest.fixture(autouse=True)
    def load(self):
        with open("/app/output/simulation_rates.json") as f:
            self.rates = json.load(f)

    def test_all_flows_present(self):
        for fid in EXPECTED_ANALYTICAL:
            assert fid in self.rates, f"Missing flow {fid}"

    def test_rates_positive(self):
        for fid, rate in self.rates.items():
            assert rate > 0, f"Flow {fid} has non-positive rate {rate}"

    @pytest.mark.parametrize("fid,expected", list(EXPECTED_ANALYTICAL.items()))
    def test_rate_accuracy(self, fid, expected):
        actual = self.rates[fid]
        rel = abs(actual - expected) / expected
        assert rel < SIM_TOLERANCE, (
            f"Simulation {fid}: expected ~{expected:.2f} Mbps, got {actual:.2f} Mbps "
            f"(error {rel:.2%}, tolerance {SIM_TOLERANCE:.0%})"
        )


class TestComparison:
    """Verify simulation-vs-analytical comparison is present and bounded."""

    @pytest.fixture(autouse=True)
    def load(self):
        with open("/app/output/comparison.json") as f:
            self.comp = json.load(f)

    def test_all_flows_present(self):
        fids = {c["flow_id"] for c in self.comp}
        for fid in EXPECTED_ANALYTICAL:
            assert fid in fids, f"Missing {fid} in comparison.json"

    def test_has_required_fields(self):
        for entry in self.comp:
            for key in ["flow_id", "simulated", "analytical", "relative_error"]:
                assert key in entry, f"Missing key '{key}' in comparison entry"

    def test_relative_errors_bounded(self):
        for entry in self.comp:
            assert entry["relative_error"] < SIM_TOLERANCE, (
                f"{entry['flow_id']}: sim={entry['simulated']:.4f}, "
                f"ana={entry['analytical']:.4f}, "
                f"rel_err={entry['relative_error']:.4%}"
            )


class TestLinkUtilization:
    """Verify link utilizations are physically consistent."""

    @pytest.fixture(autouse=True)
    def load(self):
        with open("/app/output/link_utilization.json") as f:
            self.utils = json.load(f)

    def test_all_links_present(self):
        for lid in SATURATED_LINKS + CONNECTOR_LINKS:
            assert lid in self.utils, f"Missing link {lid}"

    def test_bottleneck_links_saturated(self):
        for lid in SATURATED_LINKS:
            assert self.utils[lid] > 0.90, (
                f"Bottleneck {lid} util={self.utils[lid]:.4f}, expected near 1.0"
            )

    def test_connector_links_unsaturated(self):
        for lid in CONNECTOR_LINKS:
            assert self.utils[lid] < 0.60, (
                f"Connector {lid} util={self.utils[lid]:.4f}, expected < 0.6"
            )

    def test_no_severe_overload(self):
        for lid, u in self.utils.items():
            assert u <= 1.10, (
                f"Link {lid} util={u:.4f} exceeds capacity significantly"
            )


class TestSummary:
    """Verify summary structure, filling order, and bottleneck consistency."""

    @pytest.fixture(autouse=True)
    def load(self):
        with open("/app/output/summary.json") as f:
            self.summary = json.load(f)

    def test_total_rounds(self):
        assert "total_rounds" in self.summary
        assert isinstance(self.summary["total_rounds"], int)
        assert self.summary["total_rounds"] >= 2000, \
            f"Only {self.summary['total_rounds']} rounds — insufficient for convergence"

    def test_bottleneck_links_correct(self):
        bn = self.summary["bottleneck_links"]
        for fid, expected_link in EXPECTED_BOTTLENECKS.items():
            assert fid in bn, f"Missing bottleneck for {fid}"
            assert bn[fid] == expected_link, (
                f"{fid}: expected bottleneck {expected_link}, got {bn[fid]}"
            )

    def test_filling_order_sequence(self):
        order = self.summary["filling_order"]
        assert isinstance(order, list), "filling_order must be a list"
        assert len(order) == len(EXPECTED_FILLING_ORDER), (
            f"Expected {len(EXPECTED_FILLING_ORDER)} filling steps, got {len(order)}"
        )
        link_seq = [entry[0] for entry in order]
        assert link_seq == EXPECTED_FILLING_ORDER, (
            f"Filling order {link_seq} != expected {EXPECTED_FILLING_ORDER}"
        )

    def test_filling_rates_monotonically_increasing(self):
        order = self.summary["filling_order"]
        rates = [entry[1] for entry in order]
        for i in range(1, len(rates)):
            assert rates[i] > rates[i - 1], (
                f"Per-weight fair rates not increasing: {rates}"
            )

    def test_bottleneck_on_flow_path(self):
        bn = self.summary["bottleneck_links"]
        flows = {}
        with open("/app/flows.csv") as f:
            for row in csv.DictReader(f):
                flows[row["flow_id"]] = row["path"].split(":")
        for fid, link in bn.items():
            if fid in flows:
                assert link in flows[fid], (
                    f"{fid}: bottleneck {link} not on path {flows[fid]}"
                )


class TestConvergenceData:
    """Verify convergence.dat format and content."""

    def test_header_contains_flow_ids(self):
        with open("/app/output/convergence.dat") as f:
            header = f.readline().strip()
        if header.startswith("#"):
            header = header[1:].strip()
        fields = header.split("\t") if "\t" in header else header.split()
        assert fields[0].lower() == "round", \
            f"First column should be 'round', got '{fields[0]}'"
        for fid in EXPECTED_ANALYTICAL:
            assert fid in fields[1:], f"Missing {fid} in convergence header"

    def test_sufficient_data_rows(self):
        with open("/app/output/convergence.dat") as f:
            lines = [ln for ln in f if ln.strip() and not ln.startswith("#")]
        assert len(lines) >= 16, \
            f"Expected header + >= 15 data rows, got {len(lines)} total"

    def test_numeric_values(self):
        with open("/app/output/convergence.dat") as f:
            lines = f.readlines()
        for line in lines[1:4]:
            if not line.strip():
                continue
            vals = line.strip().split("\t") if "\t" in line else line.strip().split()
            for v in vals:
                try:
                    float(v)
                except ValueError:
                    pytest.fail(f"Non-numeric value '{v}' in convergence.dat")

    def test_rates_increase_then_stabilize(self):
        with open("/app/output/convergence.dat") as f:
            lines = [ln for ln in f if ln.strip() and not ln.startswith("#")]
        if len(lines) < 3:
            pytest.skip("Not enough data")
        first = lines[1].strip().split("\t") if "\t" in lines[1] else lines[1].strip().split()
        last = lines[-1].strip().split("\t") if "\t" in lines[-1] else lines[-1].strip().split()
        first_sum = sum(float(v) for v in first[1:])
        last_sum = sum(float(v) for v in last[1:])
        assert last_sum > first_sum, "Rates should increase from initial values"


class TestWeightedProportionality:
    """Flows sharing the same bottleneck should have weight-proportional rates."""

    @pytest.fixture(autouse=True)
    def load(self):
        with open("/app/output/simulation_rates.json") as f:
            self.rates = json.load(f)
        self.weights = {}
        with open("/app/flows.csv") as f:
            for row in csv.DictReader(f):
                self.weights[row["flow_id"]] = int(row["weight"])

    def _check_group(self, flow_ids):
        pw = {fid: self.rates[fid] / self.weights[fid] for fid in flow_ids}
        vals = list(pw.values())
        mean_pw = sum(vals) / len(vals)
        for fid, v in pw.items():
            rel = abs(v - mean_pw) / mean_pw
            assert rel < 0.12, (
                f"{fid}: per-weight rate {v:.2f} vs group mean {mean_pw:.2f} "
                f"(diff {rel:.2%})"
            )

    def test_l0_bottleneck_group(self):
        """F0(w=1), F1(w=2), F2(w=1) share bottleneck L0."""
        self._check_group(["F0", "F1", "F2"])

    def test_l1_bottleneck_group(self):
        """F3(w=1), F4(w=2), F5(w=2) share bottleneck L1."""
        self._check_group(["F3", "F4", "F5"])

    def test_l2_bottleneck_group(self):
        """F6(w=1), F7(w=2) share bottleneck L2."""
        self._check_group(["F6", "F7"])

    def test_l6_bottleneck_group(self):
        """F8(w=1), F9(w=2) share bottleneck L6."""
        self._check_group(["F8", "F9"])


class TestSimulatorGenerality:
    """Run on a second unseen topology to verify tools are not hardcoded."""

    SCENARIO2_DOT = (
        'graph test_net {\n'
        '    N0 -- N1 [id="A", capacity="30"];\n'
        '    N1 -- N2 [id="B", capacity="50"];\n'
        '    N2 -- N3 [id="C", capacity="20"];\n'
        '}\n'
    )
    SCENARIO2_CSV = (
        'flow_id,path,weight\n'
        'X,A:B,1\n'
        'Y,B:C,1\n'
        'Z,A,2\n'
    )
    # Progressive filling: A(30/3=10/w) -> C(20/1=20/w)
    # X=10, Y=20, Z=20
    EXPECTED_S2 = {"X": 10.0, "Y": 20.0, "Z": 20.0}

    def test_generality(self):
        for fn in ["topology.dot", "flows.csv"]:
            shutil.copy(f"/app/{fn}", f"/app/{fn}.bak")

        try:
            with open("/app/topology.dot", "w") as f:
                f.write(self.SCENARIO2_DOT)
            with open("/app/flows.csv", "w") as f:
                f.write(self.SCENARIO2_CSV)

            if os.path.exists("/app/output"):
                shutil.rmtree("/app/output")

            # Run available scripts
            for script in ["/app/simulate.sh", "/app/analyze.sh"]:
                if os.path.exists(script):
                    result = subprocess.run(
                        ["bash", script],
                        capture_output=True, text=True, timeout=180, cwd="/app"
                    )
                    assert result.returncode == 0, (
                        f"{script} failed on scenario 2.\n"
                        f"stdout: {result.stdout[-500:]}\n"
                        f"stderr: {result.stderr[-500:]}"
                    )

            # Verify analytical rates
            assert os.path.exists("/app/output/analytical_rates.json"), \
                "analytical_rates.json not produced for scenario 2"
            with open("/app/output/analytical_rates.json") as f:
                ana = json.load(f)
            for fid, expected in self.EXPECTED_S2.items():
                assert fid in ana, f"Missing flow {fid} in scenario 2 analytical"
                rel = abs(ana[fid] - expected) / expected
                assert rel < ANA_TOLERANCE, (
                    f"S2 analytical {fid}: expected {expected}, got {ana[fid]} "
                    f"(error {rel:.4%})"
                )

            # Verify simulation rates
            assert os.path.exists("/app/output/simulation_rates.json"), \
                "simulation_rates.json not produced for scenario 2"
            with open("/app/output/simulation_rates.json") as f:
                sim = json.load(f)
            for fid, expected in self.EXPECTED_S2.items():
                assert fid in sim, f"Missing flow {fid} in scenario 2 simulation"
                rel = abs(sim[fid] - expected) / expected
                assert rel < SIM_TOLERANCE, (
                    f"S2 simulation {fid}: expected ~{expected}, got {sim[fid]} "
                    f"(error {rel:.2%})"
                )

            # Verify convergence plot generated
            assert os.path.exists("/app/output/convergence.png"), \
                "convergence.png not generated for scenario 2"
            assert os.path.getsize("/app/output/convergence.png") > 100

        finally:
            for fn in ["topology.dot", "flows.csv"]:
                bak = f"/app/{fn}.bak"
                if os.path.exists(bak):
                    shutil.move(bak, f"/app/{fn}")

            # Restore primary output
            if os.path.exists("/app/output"):
                shutil.rmtree("/app/output")
            for script in ["/app/simulate.sh", "/app/analyze.sh"]:
                if os.path.exists(script):
                    subprocess.run(
                        ["bash", script],
                        capture_output=True, timeout=180, cwd="/app"
                    )

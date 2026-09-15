
import json
import math
import sqlite3
import subprocess
import pytest


IPC_TOL = 1e-3
POWER_TOL = 1e-2

ALL_WORKLOADS = {"matmul", "bfs", "sort", "queens", "stream", "crypto", "fft", "lzma"}
AREA_BUDGET = 28000
POWER_BUDGET = 35.0
HOT_THRESHOLD = 2500
ADJACENT_PAIRS = [(0, 1), (0, 2), (1, 3), (2, 3)]
MIN_THROUGHPUT = 30.0


def run_archsim(width, rob_size, int_regs, fp_regs, workload, paired=None):
    """Run archsim and return parsed JSON output."""
    cmd = [
        "/app/bin/archsim", "--json",
        "--width", str(width),
        "--rob-size", str(rob_size),
        "--int-regs", str(int_regs),
        "--fp-regs", str(fp_regs),
        "--workload", workload,
    ]
    if paired:
        cmd.extend(["--paired", paired])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f"archsim failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def workload_weights():
    conn = sqlite3.connect("/app/workloads.db")
    cursor = conn.execute("SELECT name, priority_weight FROM workloads")
    weights = dict(cursor.fetchall())
    conn.close()
    return weights


class TestResultsStructure:
    """Verify the output file has the required structure."""

    def test_has_required_keys(self, results):
        required = {"clusters", "total_area", "total_power_watts",
                     "weighted_throughput", "experiments_run"}
        missing = required - set(results.keys())
        assert not missing, f"results.json missing keys: {missing}"

    def test_has_four_clusters(self, results):
        assert len(results["clusters"]) == 4, (
            f"Expected 4 clusters, got {len(results['clusters'])}"
        )

    def test_cluster_structure(self, results):
        required_fields = {
            "cluster_id", "core_config", "area_per_core",
            "power_per_core_watts", "assigned_workloads",
            "solo_ipc", "interference_adjusted_ipc",
        }
        for cluster in results["clusters"]:
            missing = required_fields - set(cluster.keys())
            assert not missing, (
                f"Cluster {cluster.get('cluster_id', '?')} missing fields: {missing}"
            )

    def test_core_config_structure(self, results):
        config_fields = {"width", "rob_size", "num_int_regs", "num_fp_regs"}
        for cluster in results["clusters"]:
            missing = config_fields - set(cluster["core_config"].keys())
            assert not missing, (
                f"Cluster {cluster['cluster_id']} core_config missing: {missing}"
            )

    def test_each_cluster_has_two_workloads(self, results):
        for cluster in results["clusters"]:
            assert len(cluster["assigned_workloads"]) == 2, (
                f"Cluster {cluster['cluster_id']} has "
                f"{len(cluster['assigned_workloads'])} workloads, expected 2"
            )

    def test_all_workloads_assigned_exactly_once(self, results):
        all_wl = []
        for cluster in results["clusters"]:
            all_wl.extend(cluster["assigned_workloads"])
        assert len(all_wl) == 8, f"Expected 8 workload assignments, got {len(all_wl)}"
        assert set(all_wl) == ALL_WORKLOADS, (
            f"Workload assignment mismatch: got {set(all_wl)}, expected {ALL_WORKLOADS}"
        )
        assert len(set(all_wl)) == 8, "Some workloads assigned multiple times"

    def test_cluster_ids_are_0_to_3(self, results):
        ids = {c["cluster_id"] for c in results["clusters"]}
        assert ids == {0, 1, 2, 3}, f"Expected cluster IDs {{0,1,2,3}}, got {ids}"


class TestConstraints:
    """Verify all chip constraints are satisfied."""

    def test_total_area_budget(self, results):
        total_area = sum(c["area_per_core"] * 2 for c in results["clusters"])
        assert total_area <= AREA_BUDGET, (
            f"Total area {total_area} exceeds budget {AREA_BUDGET}"
        )
        assert results["total_area"] == total_area, (
            f"Reported total_area {results['total_area']} != computed {total_area}"
        )

    def test_total_power_budget(self, results):
        total_power = sum(c["power_per_core_watts"] * 2 for c in results["clusters"])
        assert total_power <= POWER_BUDGET + POWER_TOL, (
            f"Total power {total_power:.3f}W exceeds budget {POWER_BUDGET}W"
        )
        assert abs(results["total_power_watts"] - total_power) < POWER_TOL, (
            f"Reported total_power {results['total_power_watts']:.3f} "
            f"!= computed {total_power:.3f}"
        )

    def test_thermal_adjacency(self, results):
        """No two adjacent clusters may both be 'hot'."""
        areas = {}
        for c in results["clusters"]:
            areas[c["cluster_id"]] = c["area_per_core"]
        for a, b in ADJACENT_PAIRS:
            assert not (areas[a] > HOT_THRESHOLD and areas[b] > HOT_THRESHOLD), (
                f"Adjacent clusters {a} (area={areas[a]}) and {b} (area={areas[b]}) "
                f"are both hot (>{HOT_THRESHOLD})"
            )

    def test_positive_ipc_values(self, results):
        """All IPC values must be positive."""
        for cluster in results["clusters"]:
            for wl in cluster["assigned_workloads"]:
                assert cluster["solo_ipc"][wl] > 0, (
                    f"Cluster {cluster['cluster_id']}: solo IPC for {wl} not positive"
                )
                assert cluster["interference_adjusted_ipc"][wl] > 0, (
                    f"Cluster {cluster['cluster_id']}: adjusted IPC for {wl} not positive"
                )

    def test_interference_reduces_ipc(self, results):
        """Interference-adjusted IPC should be <= solo IPC."""
        for cluster in results["clusters"]:
            for wl in cluster["assigned_workloads"]:
                assert cluster["interference_adjusted_ipc"][wl] <= \
                       cluster["solo_ipc"][wl] + IPC_TOL, (
                    f"Cluster {cluster['cluster_id']}: adjusted IPC for {wl} "
                    f"({cluster['interference_adjusted_ipc'][wl]:.6f}) > solo IPC "
                    f"({cluster['solo_ipc'][wl]:.6f})"
                )


class TestIPCCorrectness:
    """Verify IPC values match archsim output."""

    def test_solo_ipc_values(self, results):
        """Check solo IPC for each workload against archsim."""
        for cluster in results["clusters"]:
            config = cluster["core_config"]
            for wl in cluster["assigned_workloads"]:
                sim = run_archsim(
                    config["width"], config["rob_size"],
                    config["num_int_regs"], config["num_fp_regs"], wl,
                )
                expected_ipc = sim["ipc"]
                reported_ipc = cluster["solo_ipc"][wl]
                assert abs(reported_ipc - expected_ipc) < IPC_TOL, (
                    f"Cluster {cluster['cluster_id']}, workload {wl}: "
                    f"solo IPC mismatch: reported {reported_ipc:.6f}, "
                    f"archsim says {expected_ipc:.6f}"
                )

    def test_interference_adjusted_ipc(self, results):
        """Check interference-adjusted IPC against archsim --paired."""
        for cluster in results["clusters"]:
            config = cluster["core_config"]
            wl1, wl2 = cluster["assigned_workloads"]

            sim = run_archsim(
                config["width"], config["rob_size"],
                config["num_int_regs"], config["num_fp_regs"],
                wl1, paired=wl2,
            )
            expected_ipc1 = sim["paired_ipc1"]
            expected_ipc2 = sim["paired_ipc2"]

            reported_ipc1 = cluster["interference_adjusted_ipc"][wl1]
            reported_ipc2 = cluster["interference_adjusted_ipc"][wl2]

            assert abs(reported_ipc1 - expected_ipc1) < IPC_TOL, (
                f"Cluster {cluster['cluster_id']}, {wl1} paired with {wl2}: "
                f"interference IPC mismatch: reported {reported_ipc1:.6f}, "
                f"expected {expected_ipc1:.6f}"
            )
            assert abs(reported_ipc2 - expected_ipc2) < IPC_TOL, (
                f"Cluster {cluster['cluster_id']}, {wl2} paired with {wl1}: "
                f"interference IPC mismatch: reported {reported_ipc2:.6f}, "
                f"expected {expected_ipc2:.6f}"
            )

    def test_area_per_core_correct(self, results):
        """Verify area values match archsim output."""
        for cluster in results["clusters"]:
            config = cluster["core_config"]
            wl = cluster["assigned_workloads"][0]
            sim = run_archsim(
                config["width"], config["rob_size"],
                config["num_int_regs"], config["num_fp_regs"], wl,
            )
            assert cluster["area_per_core"] == sim["area"], (
                f"Cluster {cluster['cluster_id']}: area mismatch "
                f"reported {cluster['area_per_core']}, archsim says {sim['area']}"
            )

    def test_power_per_core_correct(self, results):
        """Verify power values match archsim output."""
        for cluster in results["clusters"]:
            config = cluster["core_config"]
            wl = cluster["assigned_workloads"][0]
            sim = run_archsim(
                config["width"], config["rob_size"],
                config["num_int_regs"], config["num_fp_regs"], wl,
            )
            assert abs(cluster["power_per_core_watts"] - sim["power_watts"]) < POWER_TOL, (
                f"Cluster {cluster['cluster_id']}: power mismatch "
                f"reported {cluster['power_per_core_watts']:.4f}, "
                f"archsim says {sim['power_watts']:.4f}"
            )


class TestWeightedThroughput:
    """Verify weighted throughput calculation."""

    def test_weighted_throughput_calculation(self, results, workload_weights):
        computed = 0.0
        for cluster in results["clusters"]:
            for wl in cluster["assigned_workloads"]:
                weight = workload_weights[wl]
                adjusted_ipc = cluster["interference_adjusted_ipc"][wl]
                computed += weight * adjusted_ipc

        assert abs(results["weighted_throughput"] - computed) < IPC_TOL * 10, (
            f"Weighted throughput mismatch: reported "
            f"{results['weighted_throughput']:.6f}, computed {computed:.6f}"
        )

    def test_minimum_throughput_threshold(self, results):
        """The solution must achieve reasonable optimization quality."""
        assert results["weighted_throughput"] >= MIN_THROUGHPUT, (
            f"Weighted throughput {results['weighted_throughput']:.4f} "
            f"below minimum threshold {MIN_THROUGHPUT}. "
            f"The solution quality is too low."
        )


class TestDatabasePopulated:
    """Verify the experiments table was populated with simulation data."""

    def test_experiments_table_has_data(self):
        conn = sqlite3.connect("/app/workloads.db")
        count = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        conn.close()
        assert count >= 10, (
            f"experiments table has only {count} rows — "
            f"should contain simulation data"
        )

    def test_experiments_have_valid_schema(self):
        conn = sqlite3.connect("/app/workloads.db")
        cursor = conn.execute(
            "SELECT width, rob_size, num_int_regs, num_fp_regs, "
            "workload, ipc, area, power_watts FROM experiments LIMIT 5"
        )
        rows = cursor.fetchall()
        conn.close()
        assert len(rows) > 0, "No rows in experiments table"
        for row in rows:
            w, r, i, f, wl, ipc, area, pw = row
            assert w > 0 and r > 0 and i > 32 and f > 32, (
                f"Invalid config: {row}"
            )
            assert ipc > 0, f"IPC must be positive: {row}"
            assert area > 0, f"Area must be positive: {row}"
            assert pw > 0, f"Power must be positive: {row}"

    def test_experiments_cover_multiple_workloads(self):
        conn = sqlite3.connect("/app/workloads.db")
        cursor = conn.execute(
            "SELECT DISTINCT workload FROM experiments"
        )
        workloads = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert len(workloads) >= 4, (
            f"Experiments cover only {len(workloads)} workloads — "
            f"should explore broadly across workloads"
        )

    def test_experiments_include_paired_runs(self):
        conn = sqlite3.connect("/app/workloads.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE paired_workload IS NOT NULL"
        ).fetchone()[0]
        conn.close()
        assert count >= 4, (
            f"Only {count} paired experiments — "
            f"should characterize interference between workload pairs"
        )

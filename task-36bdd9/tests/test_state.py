
import glob
import json
import os
import re

import pytest


# ─── Fixtures ───


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def fcfs_source():
    """Locate and read the FCFS scheduler source file."""
    candidates = (
        glob.glob("/app/ramulator2/src/dram_controller/impl/scheduler/*fcfs*")
        + glob.glob("/app/ramulator2/src/dram_controller/impl/scheduler/*FCFS*")
        + glob.glob("/app/ramulator2/src/dram_controller/impl/*fcfs*")
    )
    assert len(candidates) > 0, "FCFS scheduler source file not found"
    with open(candidates[0]) as f:
        return f.read()


# ─── 1. FCFS Scheduler Implementation ───


def test_fcfs_scheduler_file_exists():
    """FCFS scheduler source file must exist."""
    candidates = (
        glob.glob("/app/ramulator2/src/dram_controller/impl/scheduler/*fcfs*")
        + glob.glob("/app/ramulator2/src/dram_controller/impl/scheduler/*FCFS*")
        + glob.glob("/app/ramulator2/src/dram_controller/impl/*fcfs*")
    )
    assert len(candidates) > 0, (
        "No FCFS scheduler source file found in "
        "src/dram_controller/impl/scheduler/"
    )


def test_fcfs_factory_registration(fcfs_source):
    """FCFS must register with Ramulator's self-registering factory."""
    assert "RAMULATOR_REGISTER_IMPLEMENTATION" in fcfs_source, (
        "FCFS source must use RAMULATOR_REGISTER_IMPLEMENTATION macro"
    )
    assert '"FCFS"' in fcfs_source or "'FCFS'" in fcfs_source, (
        "FCFS must be registered with the name \"FCFS\""
    )


def test_fcfs_inherits_ischeduler(fcfs_source):
    """FCFS must implement the IScheduler interface."""
    assert "IScheduler" in fcfs_source, (
        "FCFS must inherit from IScheduler"
    )


def test_fcfs_has_compare_method(fcfs_source):
    """FCFS must implement the compare method for request ordering."""
    assert "compare" in fcfs_source, (
        "FCFS must implement a compare method"
    )


def test_fcfs_uses_arrival_ordering(fcfs_source):
    """FCFS must use arrival-time based ordering."""
    assert "arrive" in fcfs_source, (
        "FCFS should reference request arrival time (->arrive) for ordering"
    )


def test_cmake_includes_fcfs():
    """CMakeLists.txt must include the FCFS scheduler source file."""
    with open("/app/ramulator2/src/dram_controller/CMakeLists.txt") as f:
        content = f.read().lower()
    assert "fcfs" in content, (
        "FCFS scheduler not listed in dram_controller CMakeLists.txt"
    )


# ─── 2. Build ───


def test_ramulator_binary_exists():
    """Ramulator 2.0 binary must be successfully built."""
    paths = [
        "/app/ramulator2/ramulator2",
        "/app/ramulator2/build/ramulator2",
    ]
    assert any(os.path.isfile(p) for p in paths), (
        "ramulator2 binary not found at: " + ", ".join(paths)
    )


# ─── 3. Traces ───


def test_sequential_trace_format():
    """Sequential trace must have correct SimpleO3 format."""
    path = "/app/traces/sequential.trace"
    assert os.path.isfile(path), "Sequential trace not found"
    with open(path) as f:
        lines = f.readlines()
    assert len(lines) >= 1000, (
        f"Sequential trace too short: {len(lines)} lines (need >= 1000)"
    )
    first = lines[0].strip().split()
    assert len(first) == 2, "Each line must have 2 fields: <distance> <address>"
    assert int(first[0]) == 10, f"Distance must be 10, got {first[0]}"
    assert int(first[1]) == 0, f"First sequential address must be 0, got {first[1]}"
    second = lines[1].strip().split()
    assert int(second[1]) == 64, (
        f"Second sequential address must be 64, got {second[1]}"
    )


def test_random_trace_format():
    """Random trace must have correct SimpleO3 format."""
    path = "/app/traces/random.trace"
    assert os.path.isfile(path), "Random trace not found"
    with open(path) as f:
        lines = f.readlines()
    assert len(lines) >= 1000, (
        f"Random trace too short: {len(lines)} lines (need >= 1000)"
    )
    first = lines[0].strip().split()
    assert len(first) == 2, "Each line must have 2 fields: <distance> <address>"
    assert int(first[0]) == 10, f"Distance must be 10, got {first[0]}"
    addr = int(first[1])
    assert 0 <= addr < 2**30, f"Random address must be < 2^30, got {addr}"


# ─── 4. Simulation Outputs ───


@pytest.mark.parametrize("sim_name", [
    "frfcfs_sequential", "fcfs_sequential",
    "frfcfs_random", "fcfs_random",
])
def test_simulation_output_exists(sim_name):
    """Each simulation must produce non-empty output."""
    path = f"/app/sim_output/{sim_name}.txt"
    assert os.path.isfile(path), f"Simulation output not found: {path}"
    size = os.path.getsize(path)
    assert size > 100, (
        f"Simulation output too small ({size} bytes): {path}"
    )


@pytest.mark.parametrize("sim_name", [
    "frfcfs_sequential", "fcfs_sequential",
    "frfcfs_random", "fcfs_random",
])
def test_simulation_output_has_controller_stats(sim_name):
    """Simulation output must contain DRAM controller statistics."""
    with open(f"/app/sim_output/{sim_name}.txt") as f:
        text = f.read()
    assert re.search(r"row_hits_0", text), (
        f"No row_hits_0 stat found in {sim_name}.txt"
    )
    assert re.search(r"row_misses_0", text), (
        f"No row_misses_0 stat found in {sim_name}.txt"
    )


# ─── 5. Timing Analysis (Deterministic from DDR4 source) ───
# DDR4_8Gb_x8 / DDR4_2400R: values derived from JEDEC tables and
# timing constraint formulas in Ramulator 2.0's DDR4.cpp


def test_timing_nrrds(results):
    """nRRDS = nRRDS_TABLE[dq_id=1(x8)][rate_id=3(2400)] = 4"""
    assert results["timing_analysis"]["nRRDS"] == 4


def test_timing_nrrdl(results):
    """nRRDL = nRRDL_TABLE[dq_id=1(x8)][rate_id=3(2400)] = 6"""
    assert results["timing_analysis"]["nRRDL"] == 6


def test_timing_nfaw(results):
    """nFAW = nFAW_TABLE[dq_id=1(x8)][rate_id=3(2400)] = 26"""
    assert results["timing_analysis"]["nFAW"] == 26


def test_timing_nrfc(results):
    """nRFC = ceil(360ns * 1000 / 833ps) = ceil(432.17) = 433"""
    assert results["timing_analysis"]["nRFC"] == 433


def test_timing_nrefi(results):
    """nREFI = ceil(7800ns * 1000 / 833ps) = ceil(9363.7) = 9364"""
    assert results["timing_analysis"]["nREFI"] == 9364


def test_timing_tck_ps(results):
    """tCK_ps = 1E6 / (2400/2) = 833"""
    assert results["timing_analysis"]["tCK_ps"] == 833


def test_timing_read_latency(results):
    """read_latency = nCL + nBL = 16 + 4 = 20"""
    assert results["timing_analysis"]["read_latency_cycles"] == 20


def test_timing_rank_rd_to_wr(results):
    """rank RD->WR = nCL + nBL + 2 - nCWL = 16 + 4 + 2 - 12 = 10"""
    assert results["timing_analysis"]["rank_rd_to_wr_cycles"] == 10


def test_timing_rank_wr_to_rd(results):
    """rank WR->RD = nCWL + nBL + nWTRS = 12 + 4 + 3 = 19"""
    assert results["timing_analysis"]["rank_wr_to_rd_cycles"] == 19


# ─── 6. Results Structure ───


def test_results_has_all_simulations(results):
    """results.json must have metrics for all 4 simulation runs."""
    for key in [
        "frfcfs_sequential", "fcfs_sequential",
        "frfcfs_random", "fcfs_random",
    ]:
        assert key in results["simulations"], f"Missing simulation: {key}"
        sim = results["simulations"][key]
        for field in ["row_hits", "row_misses", "row_conflicts"]:
            assert field in sim, f"{key} missing field: {field}"
            assert isinstance(sim[field], int), (
                f"{key}.{field} must be int, got {type(sim[field]).__name__}"
            )


def test_results_has_evaluation(results):
    """results.json must have a complete evaluation section."""
    ev = results["evaluation"]
    for field in [
        "sequential_optimal_scheduler",
        "random_optimal_scheduler",
        "frfcfs_row_hit_advantage_random_pct",
        "design_rationale",
    ]:
        assert field in ev, f"evaluation missing field: {field}"
    assert ev["sequential_optimal_scheduler"] in ("FRFCFS", "FCFS")
    assert ev["random_optimal_scheduler"] in ("FRFCFS", "FCFS")


# ─── 7. Evaluation Correctness ───


def test_random_optimal_is_frfcfs(results):
    """FRFCFS must be identified as optimal for random workloads.

    FRFCFS's First-Ready policy avoids scheduling commands blocked by
    DRAM timing constraints (nRRDS, nFAW, etc.), reducing idle cycles.
    It also opportunistically exploits row buffer hits when available
    in the request buffer. This is a well-established result in memory
    systems research — FRFCFS always performs >= FCFS.
    """
    assert results["evaluation"]["random_optimal_scheduler"] == "FRFCFS", (
        "FRFCFS should be identified as optimal for random workloads"
    )


def test_frfcfs_row_hit_advantage_nonnegative(results):
    """FRFCFS row hit advantage must be >= 0 for random workloads."""
    adv = results["evaluation"]["frfcfs_row_hit_advantage_random_pct"]
    assert isinstance(adv, (int, float)), "Advantage must be numeric"
    assert adv >= 0.0, (
        f"FRFCFS row hit advantage should be >= 0, got {adv}"
    )


def test_design_rationale_substantive(results):
    """Design rationale must meaningfully explain scheduling trade-offs."""
    rationale = results["evaluation"]["design_rationale"]
    assert isinstance(rationale, str), "Rationale must be a string"
    assert len(rationale) > 40, (
        f"Design rationale too short ({len(rationale)} chars)"
    )


def test_evaluation_consistent_with_metrics(results):
    """Optimal scheduler must be consistent with reported row hit data."""
    sims = results["simulations"]
    ev = results["evaluation"]

    frfcfs_hits = sims["frfcfs_random"]["row_hits"]
    fcfs_hits = sims["fcfs_random"]["row_hits"]

    if ev["random_optimal_scheduler"] == "FRFCFS":
        assert frfcfs_hits >= fcfs_hits, (
            f"Claimed FRFCFS optimal but FCFS has more row hits: "
            f"FRFCFS={frfcfs_hits}, FCFS={fcfs_hits}"
        )
    else:
        assert fcfs_hits >= frfcfs_hits, (
            f"Claimed FCFS optimal but FRFCFS has more row hits: "
            f"FRFCFS={frfcfs_hits}, FCFS={fcfs_hits}"
        )


# ─── 8. Cross-Validation with Raw Simulation Output ───


def _extract_stat_from_output(filepath, stat_name):
    """Parse an integer stat from Ramulator's YAML-formatted output."""
    with open(filepath) as f:
        text = f.read()
    m = re.search(
        rf"^\s*{re.escape(stat_name)}:\s*[\"']?(\d+)",
        text,
        re.MULTILINE,
    )
    return int(m.group(1)) if m else None


def test_frfcfs_random_cross_validation(results):
    """Verify FRFCFS random metrics match raw simulation output."""
    output_hits = _extract_stat_from_output(
        "/app/sim_output/frfcfs_random.txt", "row_hits_0"
    )
    if output_hits is not None:
        assert results["simulations"]["frfcfs_random"]["row_hits"] == output_hits, (
            f"results.json row_hits "
            f"({results['simulations']['frfcfs_random']['row_hits']}) "
            f"!= simulation output ({output_hits})"
        )


def test_fcfs_random_cross_validation(results):
    """Verify FCFS random metrics match raw simulation output."""
    output_hits = _extract_stat_from_output(
        "/app/sim_output/fcfs_random.txt", "row_hits_0"
    )
    if output_hits is not None:
        assert results["simulations"]["fcfs_random"]["row_hits"] == output_hits, (
            f"results.json row_hits "
            f"({results['simulations']['fcfs_random']['row_hits']}) "
            f"!= simulation output ({output_hits})"
        )


def test_frfcfs_geq_fcfs_random_row_hits(results):
    """FRFCFS must have >= row hits vs FCFS for random workload.

    FRFCFS is a strict generalization of FCFS: when all candidates are
    equally ready (or not ready), it falls back to FCFS ordering. Its
    First-Ready preference can only ADD row hit exploitation, never
    reduce it compared to pure FCFS.
    """
    frfcfs = results["simulations"]["frfcfs_random"]["row_hits"]
    fcfs = results["simulations"]["fcfs_random"]["row_hits"]
    assert frfcfs >= fcfs, (
        f"FRFCFS should have >= row hits for random workload: "
        f"FRFCFS={frfcfs}, FCFS={fcfs}"
    )

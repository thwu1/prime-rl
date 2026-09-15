"""
Tests for multi-accelerator systolic array fleet scheduler.

Verifies that schedule.json contains a globally optimal workload-to-accelerator
assignment with optimal per-assignment tilings and correct DAG-constrained
scheduling that minimizes makespan.

"""

import json
import math
import os
import subprocess
import pytest


def _ceildiv(a, b):
    return -(-a // b)


def _evaluate(DIM, SP_ROWS, ACC_ROWS, DMA_COST, DMA_SETUP,
              M, N, K, i_tile, j_tile, k_tile):
    """Python cycle evaluator matching accel_sim binary exactly."""
    if i_tile < 1 or j_tile < 1 or k_tile < 1:
        return -1

    sp_budget = SP_ROWS // 2
    acc_budget = ACC_ROWS // 2

    if i_tile * k_tile + k_tile * j_tile > sp_budget:
        return -1
    if i_tile * j_tile > acc_budget:
        return -1

    I_outer = _ceildiv(M, i_tile * DIM)
    J_outer = _ceildiv(N, j_tile * DIM)
    K_outer = _ceildiv(K, k_tile * DIM)

    PD = DIM - 1
    CO = 16
    total = 0

    for io in range(I_outer):
        eff_m = min(i_tile * DIM, M - io * i_tile * DIM)
        eff_i = _ceildiv(eff_m, DIM)

        for jo in range(J_outer):
            eff_n = min(j_tile * DIM, N - jo * j_tile * DIM)
            eff_j = _ceildiv(eff_n, DIM)

            ij_cyc = CO

            for ko in range(K_outer):
                eff_kd = min(k_tile * DIM, K - ko * k_tile * DIM)
                eff_k = _ceildiv(eff_kd, DIM)

                la = eff_i * eff_k * DMA_COST + DMA_SETUP
                lb = eff_k * eff_j * DMA_COST + DMA_SETUP
                tl = la + lb

                if ko == 0:
                    tl += eff_i * eff_j * DMA_COST + DMA_SETUP

                comp = eff_i * eff_j * eff_k * DIM

                if ko == 0:
                    ij_cyc += tl + comp
                else:
                    ij_cyc += max(tl, comp)

            ij_cyc += PD
            ij_cyc += eff_i * eff_j * DMA_COST + DMA_SETUP

            total += ij_cyc

    return total


def _find_optimal_tiling(accel, workload):
    """Brute-force search for optimal tiling on given accelerator."""
    DIM = accel['dim']
    SP_H = accel['sp_rows'] // 2
    ACC_H = accel['acc_rows'] // 2
    DMA = accel['dma_cost_per_row']
    DMA_S = accel['dma_setup_cost']
    M, N, K = workload['M'], workload['N'], workload['K']

    I_max = _ceildiv(M, DIM)
    J_max = _ceildiv(N, DIM)
    K_max = _ceildiv(K, DIM)

    best = float('inf')
    best_t = None

    for i in range(1, I_max + 1):
        j_lim = min(J_max, ACC_H // i)
        if j_lim < 1:
            break
        for j in range(1, j_lim + 1):
            if i * j > ACC_H:
                break
            ipj = i + j
            k_lim = min(K_max, SP_H // ipj) if ipj > 0 else K_max
            if k_lim < 1:
                continue
            for k in range(1, k_lim + 1):
                if i * k + k * j > SP_H:
                    break
                cyc = _evaluate(DIM, accel['sp_rows'], accel['acc_rows'],
                                DMA, DMA_S, M, N, K, i, j, k)
                if 0 <= cyc < best:
                    best = cyc
                    best_t = {'i_tile': i, 'j_tile': j, 'k_tile': k}

    return best, best_t


def _transfer_cost(topology, src_wl, src_accel_id, dst_accel_id):
    """Compute cross-accelerator transfer cost."""
    if src_accel_id == dst_accel_id:
        return 0
    return topology['base_latency'] + _ceildiv(
        src_wl['M'] * src_wl['N'], topology['bandwidth'])


def _compute_makespan(assignment, cycles_cache, dag, topology):
    """Compute makespan for assignment using fixed topological-order scheduling."""
    workloads = dag['workloads']
    wl_map = {w['id']: w for w in workloads}

    accel_free = {}
    end_times = {}

    for w in workloads:
        wid = w['id']
        aid = assignment[wid]

        start = accel_free.get(aid, 0)

        for pred_id in w.get('depends_on', []):
            pred_wl = wl_map[pred_id]
            transfer = _transfer_cost(topology, pred_wl,
                                      assignment[pred_id], aid)
            start = max(start, end_times[pred_id] + transfer)

        end = start + cycles_cache[(wid, aid)]
        end_times[wid] = end
        accel_free[aid] = end

    return max(end_times.values())


def _brute_force_optimal(accel_ids, wl_ids, cycles_cache, dag, topology):
    """Exhaustive search over all possible assignments."""
    n_a = len(accel_ids)
    n_w = len(wl_ids)
    best = float('inf')

    for code in range(n_a ** n_w):
        assignment = {}
        c = code
        for wid in wl_ids:
            assignment[wid] = accel_ids[c % n_a]
            c //= n_a

        ms = _compute_makespan(assignment, cycles_cache, dag, topology)
        if ms < best:
            best = ms

    return best


# ---- Fixtures ----

@pytest.fixture(scope='module')
def fleet():
    with open('/app/fleet.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def dag():
    with open('/app/dag.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def topology():
    with open('/app/topology.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def schedule():
    path = '/app/schedule.json'
    assert os.path.exists(path), "schedule.json not found at /app/schedule.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def optimal_cycles_cache(fleet, dag):
    """Pre-compute optimal cycles for every (workload, accelerator) pair."""
    cache = {}
    for accel in fleet['accelerators']:
        for wl in dag['workloads']:
            cyc, _ = _find_optimal_tiling(accel, wl)
            cache[(wl['id'], accel['id'])] = cyc
    return cache


@pytest.fixture(scope='module')
def optimal_makespan(fleet, dag, topology, optimal_cycles_cache):
    """Compute globally optimal makespan via exhaustive search."""
    accel_ids = [a['id'] for a in fleet['accelerators']]
    wl_ids = [w['id'] for w in dag['workloads']]
    return _brute_force_optimal(accel_ids, wl_ids, optimal_cycles_cache,
                                dag, topology)


# ---- Tests ----

def test_schedule_format(schedule):
    """schedule.json must have assignments list and integer makespan."""
    assert 'assignments' in schedule, "Missing 'assignments' key"
    assert 'makespan' in schedule, "Missing 'makespan' key"
    assert isinstance(schedule['assignments'], list)
    assert isinstance(schedule['makespan'], int)
    assert len(schedule['assignments']) > 0


def test_all_workloads_present(schedule, dag):
    """Every workload in the DAG must have exactly one schedule entry."""
    scheduled = {e['workload_id'] for e in schedule['assignments']}
    expected = {w['id'] for w in dag['workloads']}
    missing = expected - scheduled
    extra = scheduled - expected
    assert len(missing) == 0, f"Missing workloads: {missing}"
    assert len(extra) == 0, f"Extra workloads: {extra}"
    assert len(schedule['assignments']) == len(expected), "Duplicate entries"


def test_valid_accelerator_ids(schedule, fleet):
    """All assigned accelerator IDs must exist in the fleet."""
    valid_ids = {a['id'] for a in fleet['accelerators']}
    for entry in schedule['assignments']:
        assert entry['accelerator_id'] in valid_ids, \
            f"Unknown accelerator: {entry['accelerator_id']}"


def test_entries_have_required_fields(schedule):
    """Each assignment entry must have all required fields."""
    required = {'workload_id', 'accelerator_id', 'tiling',
                'compute_cycles', 'start_time', 'end_time'}
    for entry in schedule['assignments']:
        for field in required:
            assert field in entry, f"Missing field '{field}' in {entry}"
        t = entry['tiling']
        for dim in ('i_tile', 'j_tile', 'k_tile'):
            assert dim in t, f"Missing '{dim}' in tiling: {t}"
            assert isinstance(t[dim], int) and t[dim] >= 1, \
                f"Invalid {dim}={t[dim]}"


def test_tilings_satisfy_constraints(schedule, fleet):
    """All tilings must satisfy scratchpad and accumulator constraints."""
    accel_map = {a['id']: a for a in fleet['accelerators']}
    for entry in schedule['assignments']:
        accel = accel_map[entry['accelerator_id']]
        t = entry['tiling']
        i, j, k = t['i_tile'], t['j_tile'], t['k_tile']
        sp_budget = accel['sp_rows'] // 2
        acc_budget = accel['acc_rows'] // 2
        sp_used = i * k + k * j
        acc_used = i * j
        assert sp_used <= sp_budget, \
            f"{entry['workload_id']}: scratchpad {sp_used} > {sp_budget}"
        assert acc_used <= acc_budget, \
            f"{entry['workload_id']}: accumulator {acc_used} > {acc_budget}"


def test_cycles_match_simulator(schedule, fleet, dag):
    """Reported cycle counts must match accel_sim binary output."""
    accel_map = {a['id']: a for a in fleet['accelerators']}
    wl_map = {w['id']: w for w in dag['workloads']}
    for entry in schedule['assignments']:
        accel = accel_map[entry['accelerator_id']]
        wl = wl_map[entry['workload_id']]
        t = entry['tiling']
        result = subprocess.run(
            ['/app/accel_sim',
             str(accel['dim']), str(accel['sp_rows']),
             str(accel['acc_rows']), str(accel['dma_cost_per_row']),
             str(accel['dma_setup_cost']),
             str(wl['M']), str(wl['N']), str(wl['K']),
             str(t['i_tile']), str(t['j_tile']), str(t['k_tile'])],
            capture_output=True, text=True, timeout=10)
        expected = int(result.stdout.strip())
        assert entry['compute_cycles'] == expected, \
            (f"{entry['workload_id']}: reported {entry['compute_cycles']} "
             f"but accel_sim gives {expected}")


def test_dag_dependencies_respected(schedule, dag, fleet, topology):
    """Start times must respect DAG predecessor completion + transfer cost."""
    wl_map = {w['id']: w for w in dag['workloads']}
    entry_map = {e['workload_id']: e for e in schedule['assignments']}

    for wl in dag['workloads']:
        deps = wl.get('depends_on', [])
        if not deps:
            continue
        entry = entry_map[wl['id']]
        for pred_id in deps:
            pred_entry = entry_map[pred_id]
            pred_wl = wl_map[pred_id]
            transfer = _transfer_cost(topology, pred_wl,
                                      pred_entry['accelerator_id'],
                                      entry['accelerator_id'])
            assert entry['start_time'] >= pred_entry['end_time'] + transfer, \
                (f"{wl['id']}: start_time {entry['start_time']} < "
                 f"pred {pred_id} end {pred_entry['end_time']} + "
                 f"transfer {transfer}")


def test_accelerator_exclusivity(schedule):
    """No two workloads on the same accelerator may overlap in time."""
    by_accel = {}
    for entry in schedule['assignments']:
        by_accel.setdefault(entry['accelerator_id'], []).append(entry)

    for aid, entries in by_accel.items():
        sorted_entries = sorted(entries, key=lambda e: e['start_time'])
        for i in range(len(sorted_entries) - 1):
            assert sorted_entries[i]['end_time'] <= sorted_entries[i + 1]['start_time'], \
                (f"Overlap on {aid}: {sorted_entries[i]['workload_id']} "
                 f"ends at {sorted_entries[i]['end_time']} but "
                 f"{sorted_entries[i+1]['workload_id']} starts at "
                 f"{sorted_entries[i+1]['start_time']}")


def test_end_times_consistent(schedule):
    """end_time must equal start_time + compute_cycles for each entry."""
    for entry in schedule['assignments']:
        expected_end = entry['start_time'] + entry['compute_cycles']
        assert entry['end_time'] == expected_end, \
            (f"{entry['workload_id']}: end_time {entry['end_time']} != "
             f"start_time {entry['start_time']} + cycles {entry['compute_cycles']}")


def test_makespan_matches_schedule(schedule):
    """Reported makespan must equal max end_time across all assignments."""
    actual = max(e['end_time'] for e in schedule['assignments'])
    assert schedule['makespan'] == actual, \
        f"Reported makespan {schedule['makespan']} != actual max end {actual}"


def test_tilings_are_optimal(schedule, fleet, dag, optimal_cycles_cache):
    """Each tiling must achieve minimum cycles for its workload-accelerator pair."""
    for entry in schedule['assignments']:
        wid = entry['workload_id']
        aid = entry['accelerator_id']
        opt = optimal_cycles_cache[(wid, aid)]
        assert entry['compute_cycles'] == opt, \
            (f"{wid} on {aid}: reported {entry['compute_cycles']} "
             f"but optimal is {opt}")


def test_makespan_is_globally_optimal(schedule, optimal_makespan):
    """Makespan must equal the globally optimal over all assignments."""
    assert schedule['makespan'] == optimal_makespan, \
        (f"Makespan {schedule['makespan']} is not optimal; "
         f"best possible is {optimal_makespan}")

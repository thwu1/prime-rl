"""
Solver for multi-accelerator systolic array fleet scheduling.

Uses accel_sim binary in batch mode for tiling evaluation and exhaustive search
over all possible workload-to-accelerator assignments to minimize makespan.

"""

import json
import subprocess
import sys


def ceildiv(a, b):
    return -(-a // b)


def find_optimal_tiling_batch(accel, workload):
    """Find optimal tiling using accel_sim --batch mode."""
    dim = accel['dim']
    sp_budget = accel['sp_rows'] // 2
    acc_budget = accel['acc_rows'] // 2
    M, N, K = workload['M'], workload['N'], workload['K']

    I_max = ceildiv(M, dim)
    J_max = ceildiv(N, dim)
    K_max = ceildiv(K, dim)

    inputs = []
    for i in range(1, I_max + 1):
        j_lim = min(J_max, acc_budget // i)
        if j_lim < 1:
            break
        for j in range(1, j_lim + 1):
            if i * j > acc_budget:
                break
            ipj = i + j
            k_lim = min(K_max, sp_budget // ipj) if ipj > 0 else K_max
            if k_lim < 1:
                continue
            for k in range(1, k_lim + 1):
                if i * k + k * j > sp_budget:
                    break
                inputs.append((M, N, K, i, j, k))

    if not inputs:
        return float('inf'), None

    batch_input = '\n'.join(
        f'{m} {n} {kk} {ti} {tj} {tk}'
        for m, n, kk, ti, tj, tk in inputs
    )

    result = subprocess.run(
        ['/app/accel_sim', '--batch',
         str(accel['dim']), str(accel['sp_rows']),
         str(accel['acc_rows']), str(accel['dma_cost_per_row']),
         str(accel['dma_setup_cost'])],
        input=batch_input, capture_output=True, text=True, timeout=60)

    lines = result.stdout.strip().split('\n')
    cycles_list = [int(line) for line in lines]

    best_idx = -1
    best_cyc = float('inf')
    for idx, cyc in enumerate(cycles_list):
        if 0 <= cyc < best_cyc:
            best_cyc = cyc
            best_idx = idx

    _, _, _, bi, bj, bk = inputs[best_idx]
    return best_cyc, {'i_tile': bi, 'j_tile': bj, 'k_tile': bk}


def transfer_cost(topology, src_wl, src_accel_id, dst_accel_id):
    if src_accel_id == dst_accel_id:
        return 0
    return topology['base_latency'] + ceildiv(
        src_wl['M'] * src_wl['N'], topology['bandwidth'])


def compute_makespan(assignment, cycles_cache, dag, topology):
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
            xfer = transfer_cost(topology, pred_wl,
                                 assignment[pred_id], aid)
            start = max(start, end_times[pred_id] + xfer)

        end = start + cycles_cache[(wid, aid)]
        end_times[wid] = end
        accel_free[aid] = end

    return max(end_times.values())


def main():
    with open('/app/fleet.json') as f:
        fleet = json.load(f)
    with open('/app/dag.json') as f:
        dag = json.load(f)
    with open('/app/topology.json') as f:
        topology = json.load(f)

    accel_ids = [a['id'] for a in fleet['accelerators']]
    accel_map = {a['id']: a for a in fleet['accelerators']}
    workloads = dag['workloads']
    wl_ids = [w['id'] for w in workloads]
    wl_map = {w['id']: w for w in workloads}

    # Step 1: Find optimal tiling for each (workload, accelerator) pair
    print("Computing optimal tilings via accel_sim --batch ...")
    cycles_cache = {}
    tiling_cache = {}
    for accel in fleet['accelerators']:
        for wl in workloads:
            cyc, tiling = find_optimal_tiling_batch(accel, wl)
            cycles_cache[(wl['id'], accel['id'])] = cyc
            tiling_cache[(wl['id'], accel['id'])] = tiling
            print(f"  {wl['id']} on {accel['id']}: {cyc} cycles")

    # Step 2: Exhaustive search over all assignments
    n_a = len(accel_ids)
    n_w = len(wl_ids)
    total_assignments = n_a ** n_w
    print(f"\nSearching {n_a}^{n_w} = {total_assignments} assignments ...")

    best_ms = float('inf')
    best_assign = None

    for code in range(total_assignments):
        assignment = {}
        c = code
        for wid in wl_ids:
            assignment[wid] = accel_ids[c % n_a]
            c //= n_a

        ms = compute_makespan(assignment, cycles_cache, dag, topology)
        if ms < best_ms:
            best_ms = ms
            best_assign = assignment.copy()

    print(f"\nOptimal makespan: {best_ms}")
    for wid in wl_ids:
        print(f"  {wid} -> {best_assign[wid]}")

    # Step 3: Build schedule with start/end times
    accel_free = {}
    end_times = {}
    assignments_list = []

    for w in workloads:
        wid = w['id']
        aid = best_assign[wid]

        start = accel_free.get(aid, 0)

        for pred_id in w.get('depends_on', []):
            pred_wl = wl_map[pred_id]
            xfer = transfer_cost(topology, pred_wl,
                                 best_assign[pred_id], aid)
            start = max(start, end_times[pred_id] + xfer)

        compute = cycles_cache[(wid, aid)]
        end = start + compute
        end_times[wid] = end
        accel_free[aid] = end

        assignments_list.append({
            'workload_id': wid,
            'accelerator_id': aid,
            'tiling': tiling_cache[(wid, aid)],
            'compute_cycles': compute,
            'start_time': start,
            'end_time': end
        })

    schedule = {
        'assignments': assignments_list,
        'makespan': best_ms
    }

    with open('/app/schedule.json', 'w') as f:
        json.dump(schedule, f, indent=2)

    print(f"\nSchedule written to /app/schedule.json")


if __name__ == '__main__':
    main()

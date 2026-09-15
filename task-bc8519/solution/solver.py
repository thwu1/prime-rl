#!/usr/bin/env python3

"""
GPU Kernel Configuration Analyzer — Solution

Queries the SQLite database for hardware specs and kernel profile data,
enumerates all configurations, computes occupancy and effective arithmetic
intensity, identifies Pareto frontiers, and finds the overall best config.
"""

import json
import math
import itertools
import sqlite3


def load_inputs():
    # Load workload config
    with open('/app/workloads.json') as f:
        wl_config = json.load(f)
    target_gpu = wl_config['target_gpu']
    workloads = wl_config['workloads']

    with open('/app/search_space.json') as f:
        space = json.load(f)

    # Query SQLite database for hardware specifications
    conn = sqlite3.connect('/app/gpu_specs.db')
    cursor = conn.cursor()

    # SM resources
    cursor.execute(
        "SELECT spec_name, spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_category='sm_resources'",
        (target_gpu,)
    )
    sm = {name: int(val) for name, val in cursor.fetchall()}

    # Register specs
    cursor.execute(
        "SELECT spec_name, spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_category='registers'",
        (target_gpu,)
    )
    regs = {name: int(val) for name, val in cursor.fetchall()}

    # Shared memory specs
    cursor.execute(
        "SELECT spec_name, spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_category='shared_memory'",
        (target_gpu,)
    )
    smem = {name: int(val) for name, val in cursor.fetchall()}

    # Element size
    cursor.execute(
        "SELECT spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_name='fp16_element_size'",
        (target_gpu,)
    )
    element_size = int(cursor.fetchone()[0])

    # Kernel profile: register overhead for tiled_matmul
    cursor.execute(
        "SELECT value FROM kernel_profiles "
        "WHERE kernel_type='tiled_matmul' AND parameter='register_overhead_per_thread'"
    )
    reg_overhead = int(cursor.fetchone()[0])

    conn.close()

    hw = {
        'num_sms': sm['num_sms'],
        'max_warps_per_sm': sm['max_warps_per_sm'],
        'max_blocks_per_sm': sm['max_blocks_per_sm'],
        'warp_size': sm['warp_size'],
        'register_file_size': regs['register_file_size'],
        'max_registers_per_thread': regs['max_registers_per_thread'],
        'allocation_granularity': regs['allocation_granularity'],
        'shared_memory_per_sm': smem['shared_memory_per_sm'],
        'max_shared_memory_per_block': smem['max_shared_memory_per_block'],
        'element_size_bytes': element_size,
        'register_overhead': reg_overhead,
    }

    return hw, space, workloads


def generate_configs(space):
    """Enumerate all configurations from the search space."""
    keys = ['BLOCK_SIZE_M', 'BLOCK_SIZE_N', 'BLOCK_SIZE_K',
            'GROUP_SIZE_M', 'num_warps', 'num_stages']
    values = [space[k] for k in keys]
    configs = []
    for combo in itertools.product(*values):
        configs.append(dict(zip(keys, combo)))
    return configs


def analyze_config(cfg, hw, workload):
    """
    Compute occupancy, effective arithmetic intensity, and score
    for a single (config, workload) pair.

    Returns None if the config violates hardware constraints.
    """
    bm = cfg['BLOCK_SIZE_M']
    bn = cfg['BLOCK_SIZE_N']
    bk = cfg['BLOCK_SIZE_K']
    gm = cfg['GROUP_SIZE_M']
    nw = cfg['num_warps']
    ns = cfg['num_stages']

    M = workload['M']
    N = workload['N']
    K = workload['K']
    es = hw['element_size_bytes']
    ws = hw['warp_size']

    # ----- Shared memory per CTA -----
    smem_per_stage = (bm * bk + bk * bn) * es
    smem = ns * smem_per_stage

    if smem > hw['max_shared_memory_per_block']:
        return None

    # ----- Register pressure -----
    threads_per_cta = nw * ws
    acc_regs_per_thread = (bm * bn) // threads_per_cta
    total_regs_per_thread = acc_regs_per_thread + hw['register_overhead']

    if total_regs_per_thread > hw['max_registers_per_thread']:
        return None

    alloc_regs = math.ceil(total_regs_per_thread / hw['allocation_granularity']) * hw['allocation_granularity']
    regs_per_cta = alloc_regs * threads_per_cta

    # ----- Occupancy: active CTAs per SM -----
    blocks_by_warps = hw['max_warps_per_sm'] // nw
    blocks_by_smem = (hw['shared_memory_per_sm'] // smem
                      if smem > 0 else hw['max_blocks_per_sm'])
    blocks_by_regs = (hw['register_file_size'] // regs_per_cta
                      if regs_per_cta > 0 else hw['max_blocks_per_sm'])
    blocks_by_max = hw['max_blocks_per_sm']

    active_blocks = min(blocks_by_warps, blocks_by_smem,
                        blocks_by_regs, blocks_by_max)

    if active_blocks < 1:
        return None

    occupancy = active_blocks * nw / hw['max_warps_per_sm']

    # ----- Bottleneck identification -----
    limits = [
        ('smem', blocks_by_smem),
        ('regs', blocks_by_regs),
        ('warps', blocks_by_warps),
        ('max_blocks', blocks_by_max),
    ]
    priority = {'smem': 0, 'regs': 1, 'warps': 2, 'max_blocks': 3}
    bottleneck = min(limits, key=lambda x: (x[1], priority[x[0]]))[0]

    # ----- Effective arithmetic intensity with L2 cache reuse -----
    num_row_tiles = math.ceil(M / bm)
    effective_group = min(gm, num_row_tiles)

    bytes_a = bm * K * es
    bytes_b = bn * K * es / effective_group
    bytes_c = bm * bn * es

    effective_bytes = bytes_a + bytes_b + bytes_c
    tile_flops = 2.0 * bm * bn * K
    effective_ai = tile_flops / effective_bytes

    # ----- Score -----
    score = occupancy * effective_ai

    return {
        'BLOCK_SIZE_M': bm,
        'BLOCK_SIZE_N': bn,
        'BLOCK_SIZE_K': bk,
        'GROUP_SIZE_M': gm,
        'num_warps': nw,
        'num_stages': ns,
        'occupancy': occupancy,
        'effective_ai': effective_ai,
        'score': score,
        'smem_bytes': smem,
        'bottleneck': bottleneck,
    }


def sort_key(r):
    """Tiebreaker for configs with equal scores."""
    return (
        -r['score'],
        r['smem_bytes'],
        r['num_warps'],
        r['BLOCK_SIZE_M'],
        r['BLOCK_SIZE_N'],
        r['BLOCK_SIZE_K'],
        r['GROUP_SIZE_M'],
        r['num_stages'],
    )


def compute_pareto(valid_results):
    """
    Compute deduplicated Pareto frontier on (occupancy, effective_ai).
    """
    points = {}
    for r in valid_results:
        key = (r['occupancy'], r['effective_ai'])
        if key not in points or sort_key(r) < sort_key(points[key]):
            points[key] = r

    reps = list(points.values())

    pareto = []
    for r in reps:
        dominated = False
        for other in reps:
            if other is r:
                continue
            if (other['occupancy'] >= r['occupancy']
                    and other['effective_ai'] >= r['effective_ai']
                    and (other['occupancy'] > r['occupancy']
                         or other['effective_ai'] > r['effective_ai'])):
                dominated = True
                break
        if not dominated:
            pareto.append(r)

    pareto.sort(key=sort_key)
    return pareto


def main():
    hw, space, workloads = load_inputs()

    configs = generate_configs(space)
    total_configs = len(configs)
    print(f"Total configurations: {total_configs}")

    all_scores = {}

    output = {'workloads': []}

    for wi, wl in enumerate(workloads):
        M, N, K = wl['M'], wl['N'], wl['K']
        print(f"\nWorkload {wi+1}: M={M}, N={N}, K={K}")

        valid = []
        for cfg in configs:
            result = analyze_config(cfg, hw, wl)
            if result is not None:
                valid.append(result)

        print(f"  Valid configs: {len(valid)}")

        pareto = compute_pareto(valid)
        print(f"  Pareto frontier points: {len(pareto)}")

        valid.sort(key=sort_key)
        best = valid[0] if valid else None

        if best:
            print(f"  Best: BM={best['BLOCK_SIZE_M']}, BN={best['BLOCK_SIZE_N']}, "
                  f"BK={best['BLOCK_SIZE_K']}, GM={best['GROUP_SIZE_M']}, "
                  f"nw={best['num_warps']}, ns={best['num_stages']}")
            print(f"    occ={best['occupancy']:.4f}, eai={best['effective_ai']:.2f}, "
                  f"score={best['score']:.2f}, smem={best['smem_bytes']}, "
                  f"bottleneck={best['bottleneck']}")

        output['workloads'].append({
            'M': M, 'N': N, 'K': K,
            'total_configs': total_configs,
            'num_valid': len(valid),
            'num_pareto': len(pareto),
            'best': best,
            'pareto_frontier': pareto,
        })

        for r in valid:
            key = (r['BLOCK_SIZE_M'], r['BLOCK_SIZE_N'], r['BLOCK_SIZE_K'],
                   r['GROUP_SIZE_M'], r['num_warps'], r['num_stages'])
            if key not in all_scores:
                all_scores[key] = {}
            all_scores[key][wi] = r['score']

    # ----- Overall best: geometric mean across all workloads -----
    num_wl = len(workloads)
    best_geo_score = -1.0
    best_geo_key = None

    for key, scores_map in all_scores.items():
        if len(scores_map) == num_wl:
            vals = [scores_map[i] for i in range(num_wl)]
            geo = math.prod(vals) ** (1.0 / num_wl)
            if geo > best_geo_score:
                best_geo_score = geo
                best_geo_key = key

    if best_geo_key:
        cfg_dict = {
            'BLOCK_SIZE_M': best_geo_key[0],
            'BLOCK_SIZE_N': best_geo_key[1],
            'BLOCK_SIZE_K': best_geo_key[2],
            'GROUP_SIZE_M': best_geo_key[3],
            'num_warps': best_geo_key[4],
            'num_stages': best_geo_key[5],
        }
        r = analyze_config(cfg_dict, hw, workloads[0])
        overall = dict(r)
        overall['geo_mean_score'] = best_geo_score
        output['overall_best'] = overall

        print(f"\nOverall best (geo mean = {best_geo_score:.2f}):")
        print(f"  BM={cfg_dict['BLOCK_SIZE_M']}, BN={cfg_dict['BLOCK_SIZE_N']}, "
              f"BK={cfg_dict['BLOCK_SIZE_K']}, GM={cfg_dict['GROUP_SIZE_M']}, "
              f"nw={cfg_dict['num_warps']}, ns={cfg_dict['num_stages']}")

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == '__main__':
    main()

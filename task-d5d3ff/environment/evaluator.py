"""
Performance evaluator for a Gemmini-like systolic array accelerator.

Models cycle-level performance of matrix multiplications (C = A * B + D) on a
systolic array with decoupled access-execute architecture and double-buffered
scratchpad/accumulator memories.

Hardware model:
  - DIM x DIM systolic array processes one DIM-row per cycle (pipelined)
  - Scratchpad stores A (input) and B (weight) tiles in inputType rows
  - Accumulator stores C (output) and D (bias) tiles in accType rows
  - Both memories are double-buffered: only half capacity available per buffer
  - DMA engine moves data between main memory and local SRAMs
  - Each DMA load operation incurs a fixed setup overhead for TLB lookup and
    TileLink address negotiation, independent of transfer size

Tiling strategy:
  A[M,K] is tiled into blocks of (i_tile*DIM) x (k_tile*DIM)
  B[K,N] is tiled into blocks of (k_tile*DIM) x (j_tile*DIM)
  C[M,N] / D[M,N] are tiled into blocks of (i_tile*DIM) x (j_tile*DIM)

  Scratchpad holds: i_tile*k_tile rows for A + k_tile*j_tile rows for B
  Accumulator holds: i_tile*j_tile rows for C/D

Scheduling:
  The outer loops iterate over (I_outer, J_outer) pairs. For each pair, the
  inner loop iterates over K_outer steps, accumulating partial sums.

  - First K iteration (cold start): loads are fully serialized before compute
  - Subsequent K iterations: loads overlap with compute via double-buffering
  - After all K iterations: result C is stored back to main memory
  - Pipeline drain: DIM-1 cycles after the last compute in each (i,j) group
  - Configuration overhead: fixed cost per (i,j) group for setting up DMA/compute
  - DMA setup: fixed per-transaction cost for TLB + TileLink handshake

"""

import math
import json
import sys


def evaluate_tiling(hw_config, workload, tiling):
    """
    Compute total execution cycles for a given tiling strategy.

    Args:
        hw_config: dict with 'dim', 'sp_rows', 'acc_rows', 'dma_cost_per_row',
                   'dma_setup_cost'
        workload: dict with 'M', 'N', 'K'
        tiling: dict with 'i_tile', 'j_tile', 'k_tile' (in units of DIM rows)

    Returns:
        dict with 'cycles' (int or inf), 'valid' (bool), 'error' (str)
    """
    DIM = hw_config['dim']
    SP_ROWS = hw_config['sp_rows']
    ACC_ROWS = hw_config['acc_rows']
    DMA_COST = hw_config['dma_cost_per_row']
    DMA_SETUP = hw_config['dma_setup_cost']

    i_tile = tiling['i_tile']
    j_tile = tiling['j_tile']
    k_tile = tiling['k_tile']

    M = workload['M']
    N = workload['N']
    K = workload['K']

    if i_tile < 1 or j_tile < 1 or k_tile < 1:
        return {'cycles': float('inf'), 'valid': False,
                'error': 'All tiling factors must be >= 1'}

    # Scratchpad: A_tile + B_tile must fit in one buffer (half of total)
    sp_a_rows = i_tile * k_tile
    sp_b_rows = k_tile * j_tile
    sp_needed = sp_a_rows + sp_b_rows
    sp_budget = SP_ROWS // 2
    if sp_needed > sp_budget:
        return {'cycles': float('inf'), 'valid': False,
                'error': f'Scratchpad overflow: {sp_needed} > {sp_budget}'}

    # Accumulator: C/D tile must fit in one buffer (half of total)
    acc_needed = i_tile * j_tile
    acc_budget = ACC_ROWS // 2
    if acc_needed > acc_budget:
        return {'cycles': float('inf'), 'valid': False,
                'error': f'Accumulator overflow: {acc_needed} > {acc_budget}'}

    I_outer = math.ceil(M / (i_tile * DIM))
    J_outer = math.ceil(N / (j_tile * DIM))
    K_outer = math.ceil(K / (k_tile * DIM))

    PIPELINE_DRAIN = DIM - 1
    CONFIG_OVERHEAD = 16

    total_cycles = 0

    for i_o in range(I_outer):
        for j_o in range(J_outer):
            eff_m = min(i_tile * DIM, M - i_o * i_tile * DIM)
            eff_n = min(j_tile * DIM, N - j_o * j_tile * DIM)
            eff_i = math.ceil(eff_m / DIM)
            eff_j = math.ceil(eff_n / DIM)

            ij_cycles = CONFIG_OVERHEAD

            for k_o in range(K_outer):
                eff_k_dim = min(k_tile * DIM, K - k_o * k_tile * DIM)
                eff_k = math.ceil(eff_k_dim / DIM)

                # DMA load costs: data transfer + per-transaction setup
                load_a = eff_i * eff_k * DMA_COST + DMA_SETUP
                load_b = eff_k * eff_j * DMA_COST + DMA_SETUP
                total_load = load_a + load_b

                # Load bias D only on first K iteration
                if k_o == 0:
                    load_d = eff_i * eff_j * DMA_COST + DMA_SETUP
                    total_load += load_d

                # Systolic array compute cost
                compute = eff_i * eff_j * eff_k * DIM

                # First K iteration: cold start (no overlap)
                # Subsequent iterations: overlap load and compute
                if k_o == 0:
                    ij_cycles += total_load + compute
                else:
                    ij_cycles += max(total_load, compute)

            # Pipeline drain after last compute
            ij_cycles += PIPELINE_DRAIN

            # Store result C back to main memory
            store_c = eff_i * eff_j * DMA_COST + DMA_SETUP
            ij_cycles += store_c

            total_cycles += ij_cycles

    return {'cycles': total_cycles, 'valid': True, 'error': ''}


def main():
    """CLI: evaluate a schedule against workloads."""
    if len(sys.argv) == 4:
        with open(sys.argv[1]) as f:
            hw = json.load(f)
        with open(sys.argv[2]) as f:
            workloads = json.load(f)
        with open(sys.argv[3]) as f:
            schedule = json.load(f)

        total = 0
        for entry in schedule:
            wl = next(w for w in workloads if w['name'] == entry['name'])
            result = evaluate_tiling(hw, wl, entry['tiling'])
            status = "VALID" if result['valid'] else f"INVALID: {result['error']}"
            print(f"{entry['name']}: {result['cycles']} cycles [{status}]")
            if result['valid']:
                total += result['cycles']
        print(f"\nTotal: {total} cycles")
    elif len(sys.argv) == 6:
        with open(sys.argv[1]) as f:
            hw = json.load(f)
        workload = json.loads(sys.argv[2])
        tiling = {'i_tile': int(sys.argv[3]), 'j_tile': int(sys.argv[4]),
                  'k_tile': int(sys.argv[5])}
        result = evaluate_tiling(hw, workload, tiling)
        print(json.dumps(result, indent=2))
    else:
        print("Usage:")
        print("  Batch:  python3 evaluator.py hw_config.json workloads.json schedule.json")
        print("  Single: python3 evaluator.py hw_config.json '{\"M\":64,\"N\":64,\"K\":64}' i j k")
        sys.exit(1)


if __name__ == '__main__':
    main()

"""
Optimal tiling solver for a Gemmini-like systolic array accelerator.

Uses brute-force search with an O(1) analytical performance evaluator to find
the globally optimal (i_tile, j_tile, k_tile) for each workload.

"""

import json
import math
import sys


def ceildiv(a, b):
    return -(-a // b)


def fast_eval(DIM, SP_H, ACC_H, DMA, DMA_S, M, N, K, it, jt, kt):
    """
    O(1) analytical cycle count evaluation.

    Decomposes the outer (I,J) loop into four categories based on whether each
    dimension has a partial edge tile, then computes each category's K-loop cost
    analytically by separating cold-start, full-overlap, and partial-edge-K
    iterations.
    """
    if it * kt + kt * jt > SP_H or it * jt > ACC_H:
        return float('inf')

    PD = DIM - 1
    CO = 16

    Io = ceildiv(M, it * DIM)
    Jo = ceildiv(N, jt * DIM)
    Ko = ceildiv(K, kt * DIM)

    rm = M % (it * DIM)
    rn = N % (jt * DIM)
    rk = K % (kt * DIM)

    has_ei = 1 if rm > 0 else 0
    has_ej = 1 if rn > 0 else 0
    has_ek = rk > 0

    fi, fj = it, jt
    pi = ceildiv(rm, DIM) if has_ei else it
    pj = ceildiv(rn, DIM) if has_ej else jt
    pk = ceildiv(rk, DIM) if has_ek else kt

    def ij_cost(ei, ej):
        c = CO
        if Ko == 1:
            ek = ceildiv(K, DIM)
            la = ei * ek * DMA + DMA_S
            lb = ek * ej * DMA + DMA_S
            ld = ei * ej * DMA + DMA_S
            c += la + lb + ld + ei * ej * ek * DIM
        else:
            # First K iteration: cold start, no overlap
            la0 = ei * kt * DMA + DMA_S
            lb0 = kt * ej * DMA + DMA_S
            ld0 = ei * ej * DMA + DMA_S
            c += la0 + lb0 + ld0 + ei * ej * kt * DIM

            # Middle K iterations: overlapped
            la_m = ei * kt * DMA + DMA_S
            lb_m = kt * ej * DMA + DMA_S
            tl_m = la_m + lb_m
            cp_m = ei * ej * kt * DIM
            ov_m = max(tl_m, cp_m)

            if has_ek:
                mid = Ko - 2
                if mid > 0:
                    c += mid * ov_m
                la_l = ei * pk * DMA + DMA_S
                lb_l = pk * ej * DMA + DMA_S
                tl_l = la_l + lb_l
                cp_l = ei * ej * pk * DIM
                c += max(tl_l, cp_l)
            else:
                c += (Ko - 1) * ov_m

        c += PD + ei * ej * DMA + DMA_S  # drain + store
        return c

    nff = (Io - has_ei) * (Jo - has_ej)
    nei = has_ei * (Jo - has_ej)
    nej = (Io - has_ei) * has_ej
    nco = has_ei * has_ej

    t = 0
    if nff > 0:
        t += nff * ij_cost(fi, fj)
    if nei > 0:
        t += nei * ij_cost(pi, fj)
    if nej > 0:
        t += nej * ij_cost(fi, pj)
    if nco > 0:
        t += nco * ij_cost(pi, pj)
    return t


def find_optimal(hw, wl):
    """Brute-force search for globally optimal tiling."""
    DIM = hw['dim']
    SP_H = hw['sp_rows'] // 2
    ACC_H = hw['acc_rows'] // 2
    DMA = hw['dma_cost_per_row']
    DMA_S = hw['dma_setup_cost']
    M, N, K = wl['M'], wl['N'], wl['K']

    I_max = ceildiv(M, DIM)
    J_max = ceildiv(N, DIM)
    K_max = ceildiv(K, DIM)

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
                cyc = fast_eval(DIM, SP_H, ACC_H, DMA, DMA_S,
                                M, N, K, i, j, k)
                if cyc < best:
                    best = cyc
                    best_t = {'i_tile': i, 'j_tile': j, 'k_tile': k}

    return best, best_t


def main():
    with open('/app/hw_config.json') as f:
        hw = json.load(f)
    with open('/app/workloads.json') as f:
        workloads = json.load(f)

    # Also load the loop-based evaluator for cross-validation
    sys.path.insert(0, '/app')
    from evaluator import evaluate_tiling

    schedule = []
    for wl in workloads:
        opt_cycles, opt_tiling = find_optimal(hw, wl)

        # Cross-validate against loop-based evaluator
        result = evaluate_tiling(hw, wl, opt_tiling)
        assert result['valid'], f"Invalid tiling for {wl['name']}: {result['error']}"
        assert result['cycles'] == opt_cycles, \
            f"Mismatch for {wl['name']}: analytical={opt_cycles}, loop={result['cycles']}"

        schedule.append({
            'name': wl['name'],
            'tiling': opt_tiling,
            'cycles': opt_cycles
        })
        print(f"{wl['name']}: {opt_cycles} cycles with tiling {opt_tiling}")

    with open('/app/schedule.json', 'w') as f:
        json.dump(schedule, f, indent=2)

    total = sum(e['cycles'] for e in schedule)
    print(f"\nTotal: {total} cycles")
    print("Schedule written to /app/schedule.json")


if __name__ == '__main__':
    main()

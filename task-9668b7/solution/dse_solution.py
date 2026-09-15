#!/usr/bin/env python3
"""
HLS Design Space Exploration Analyzer.

Implements configuration expansion, cost model evaluation via ctypes FFI,
multi-objective Pareto analysis, 3D hypervolume computation, exclusive
contributions, and front reduction.
"""

import ctypes
import yaml
import json
import sys
import argparse
from itertools import product


# ---------------------------------------------------------------------------
# ctypes interface to libhls_cost.so
# ---------------------------------------------------------------------------

class HLSConfig(ctypes.Structure):
    _fields_ = [
        ("clock_period_ns", ctypes.c_double),
        ("enable_pipeline", ctypes.c_int),
        ("pipeline_ii", ctypes.c_int),
        ("enable_dataflow", ctypes.c_int),
        ("unroll_factor", ctypes.c_int),
        ("array_partition_factor", ctypes.c_int),
        ("allocation_limit_add", ctypes.c_int),
        ("dsp_full_reg", ctypes.c_int),
        ("vivado_strategy", ctypes.c_int),
    ]


class HLSMetrics(ctypes.Structure):
    _fields_ = [
        ("area_luts", ctypes.c_double),
        ("latency_ns", ctypes.c_double),
        ("power_mw", ctypes.c_double),
    ]


STRATEGY_MAP = {"Default": 0, "Performance_Explore": 1, "Area_Explore": 2}

_lib = ctypes.CDLL("/app/libhls_cost.so")
_lib.hls_evaluate.argtypes = [ctypes.POINTER(HLSConfig), ctypes.POINTER(HLSMetrics)]
_lib.hls_evaluate.restype = None
_lib.hls_evaluate_batch.argtypes = [
    ctypes.POINTER(HLSConfig), ctypes.c_int, ctypes.POINTER(HLSMetrics)
]
_lib.hls_evaluate_batch.restype = None


# ---------------------------------------------------------------------------
# Configuration expansion
# ---------------------------------------------------------------------------

def expand_configurations(yaml_config):
    """Expand DSE parameter space with constraint-aware pruning."""
    params = yaml_config['parameters']
    constraints = yaml_config.get('constraints', [])

    constraint_map = {}
    for c in constraints:
        constraint_map[c['dependent']] = {
            'depends_on': c['depends_on'],
            'condition': c['condition'],
            'default': c['default_when_inactive']
        }

    param_names = list(params.keys())
    param_values = [params[name] for name in param_names]

    configs = []
    for combo in product(*param_values):
        config = dict(zip(param_names, combo))
        valid = True
        for dep_param, rule in constraint_map.items():
            if config[rule['depends_on']] != rule['condition']:
                if config[dep_param] != rule['default']:
                    valid = False
                    break
        if valid:
            configs.append(config)

    return configs


# ---------------------------------------------------------------------------
# Evaluation via shared library
# ---------------------------------------------------------------------------

def _dict_to_struct(config):
    """Convert a Python config dict to an HLSConfig ctypes struct."""
    c = HLSConfig()
    c.clock_period_ns = float(config['clock_period_ns'])
    c.enable_pipeline = int(bool(config['enable_pipeline']))
    c.pipeline_ii = int(config['pipeline_ii'])
    c.enable_dataflow = int(bool(config['enable_dataflow']))
    c.unroll_factor = int(config['unroll_factor'])
    c.array_partition_factor = int(config['array_partition_factor'])
    c.allocation_limit_add = int(config['allocation_limit_add'])
    c.dsp_full_reg = int(bool(config['dsp_full_reg']))
    c.vivado_strategy = STRATEGY_MAP[config['vivado_strategy']]
    return c


def evaluate_all(configs):
    """Evaluate all configurations using the C shared library via ctypes."""
    n = len(configs)
    ConfigArray = HLSConfig * n
    MetricsArray = HLSMetrics * n

    c_configs = ConfigArray()
    for i, config in enumerate(configs):
        c_configs[i] = _dict_to_struct(config)

    c_metrics = MetricsArray()
    _lib.hls_evaluate_batch(c_configs, n, c_metrics)

    results = []
    for i in range(n):
        results.append({
            'config': dict(configs[i]),
            'metrics': {
                'area_luts': round(c_metrics[i].area_luts, 4),
                'latency_ns': round(c_metrics[i].latency_ns, 4),
                'power_mw': round(c_metrics[i].power_mw, 4)
            }
        })
    return results


# ---------------------------------------------------------------------------
# Pareto dominance analysis
# ---------------------------------------------------------------------------

def _dominates(a, b, objectives):
    """Check if point a dominates point b (all objectives minimized)."""
    any_lt = False
    for obj in objectives:
        va, vb = a[obj], b[obj]
        if va > vb:
            return False
        if va < vb:
            any_lt = True
    return any_lt


def pareto_front(points, objectives):
    """Return indices of non-dominated points."""
    n = len(points)
    is_dominated = [False] * n

    for i in range(n):
        if is_dominated[i]:
            continue
        for j in range(n):
            if i == j or is_dominated[j]:
                continue
            if _dominates(points[j], points[i], objectives):
                is_dominated[i] = True
                break

    return [i for i in range(n) if not is_dominated[i]]


def non_dominated_sort(points, objectives):
    """Assign Pareto ranks (1-indexed) to all points."""
    n = len(points)
    M = len(objectives)

    obj_vals = [tuple(p[obj] for obj in objectives) for p in points]

    domination_count = [0] * n
    dominated_set = [[] for _ in range(n)]

    for i in range(n):
        vi = obj_vals[i]
        for j in range(i + 1, n):
            vj = obj_vals[j]

            i_dom_j = True
            j_dom_i = True
            i_strict = False
            j_strict = False

            for k in range(M):
                a, b = vi[k], vj[k]
                if a > b:
                    i_dom_j = False
                    j_strict = True
                elif a < b:
                    j_dom_i = False
                    i_strict = True

                if not i_dom_j and not j_dom_i:
                    break

            if i_dom_j and i_strict:
                dominated_set[i].append(j)
                domination_count[j] += 1
            elif j_dom_i and j_strict:
                dominated_set[j].append(i)
                domination_count[i] += 1

    ranks = [0] * n
    current_front = [i for i in range(n) if domination_count[i] == 0]
    rank = 0

    while current_front:
        rank += 1
        next_front = []
        for i in current_front:
            ranks[i] = rank
            for j in dominated_set[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    next_front.append(j)
        current_front = next_front

    return ranks


# ---------------------------------------------------------------------------
# Hypervolume computation
# ---------------------------------------------------------------------------

def _hv_2d(points_2d, ref_2d):
    """Compute 2D hypervolume using a sweep-line on the non-dominated set."""
    pts = [(x, y) for x, y in points_2d if x < ref_2d[0] and y < ref_2d[1]]
    if not pts:
        return 0.0

    pts.sort()

    nd = []
    best_y = float('inf')
    for x, y in pts:
        if y < best_y:
            nd.append((x, y))
            best_y = y

    hv = 0.0
    for i, (x, y) in enumerate(nd):
        next_x = nd[i + 1][0] if i + 1 < len(nd) else ref_2d[0]
        hv += (next_x - x) * (ref_2d[1] - y)

    return hv


def hypervolume_3d(front_points, ref):
    """Compute 3D hypervolume via z-axis slicing."""
    pts = [(x, y, z) for x, y, z in front_points
           if x < ref[0] and y < ref[1] and z < ref[2]]

    if not pts:
        return 0.0

    pts.sort(key=lambda p: p[2])

    z_groups = []
    i = 0
    while i < len(pts):
        z_val = pts[i][2]
        group = []
        while i < len(pts) and pts[i][2] == z_val:
            group.append(pts[i])
            i += 1
        z_groups.append((z_val, group))

    hv = 0.0
    active_2d = []

    for gi, (z_val, group) in enumerate(z_groups):
        for x, y, z in group:
            active_2d.append((x, y))

        if gi + 1 < len(z_groups):
            z_next = z_groups[gi + 1][0]
        else:
            z_next = ref[2]

        dz = z_next - z_val
        area = _hv_2d(active_2d, (ref[0], ref[1]))
        hv += area * dz

    return hv


# ---------------------------------------------------------------------------
# Exclusive contributions and front reduction
# ---------------------------------------------------------------------------

def exclusive_contributions(front_points, ref):
    """Compute exclusive hypervolume contribution of each point."""
    total_hv = hypervolume_3d(front_points, ref)
    contributions = []

    for i in range(len(front_points)):
        remaining = [p for j, p in enumerate(front_points) if j != i]
        hv_without = hypervolume_3d(remaining, ref) if remaining else 0.0
        contributions.append(total_hv - hv_without)

    return contributions


def greedy_reduce(front_points, ref, max_k):
    """Reduce front to at most max_k points by iterative minimum-contribution removal."""
    if max_k >= len(front_points):
        return list(range(len(front_points)))

    active = list(range(len(front_points)))

    while len(active) > max_k:
        current_pts = [front_points[i] for i in active]
        contribs = exclusive_contributions(current_pts, ref)
        min_idx = min(range(len(contribs)), key=lambda i: contribs[i])
        active.pop(min_idx)

    return active


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='HLS DSE Analyzer')
    parser.add_argument('--config', required=True, help='YAML config file path')
    parser.add_argument('--output', required=True, help='Output JSON file path')
    parser.add_argument('--max-points', type=int, default=None,
                        help='Maximum Pareto front points to keep')
    args = parser.parse_args()

    with open(args.config) as f:
        yaml_config = yaml.safe_load(f)

    configs = expand_configurations(yaml_config)
    evaluated = evaluate_all(configs)

    objectives = [obj['name'] for obj in yaml_config['objectives']]
    metrics_list = [e['metrics'] for e in evaluated]

    ranks = non_dominated_sort(metrics_list, objectives)
    num_ranks = max(ranks) if ranks else 0
    front_indices = [i for i, r in enumerate(ranks) if r == 1]

    front_metrics = [metrics_list[i] for i in front_indices]
    front_tuples = [(m[objectives[0]], m[objectives[1]], m[objectives[2]])
                    for m in front_metrics]

    ref_dict = yaml_config['reference_point']
    ref_tuple = (ref_dict[objectives[0]], ref_dict[objectives[1]],
                 ref_dict[objectives[2]])

    hv = hypervolume_3d(front_tuples, ref_tuple)
    contribs = exclusive_contributions(front_tuples, ref_tuple)

    pareto_output = []
    for idx, fi in enumerate(front_indices):
        pareto_output.append({
            'config': evaluated[fi]['config'],
            'metrics': evaluated[fi]['metrics'],
            'contribution': round(contribs[idx], 6)
        })

    result = {
        'total_configurations': len(configs),
        'num_pareto_optimal': len(front_indices),
        'num_ranks': num_ranks,
        'pareto_front': pareto_output,
        'hypervolume': round(hv, 6),
        'reference_point': ref_dict
    }

    if args.max_points is not None and args.max_points < len(front_indices):
        keep = greedy_reduce(front_tuples, ref_tuple, args.max_points)
        result['reduced_front'] = [pareto_output[i] for i in keep]

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Analysis complete. {len(configs)} configurations, "
          f"{len(front_indices)} Pareto-optimal, HV={hv:.2f}")


if __name__ == '__main__':
    main()

"""
Pytest tests for the constrained floorplanning optimizer.


Tests verify that the optimizer produces feasible, high-quality
solutions for all five instances.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, '/app')
from evaluator import evaluate_solution, compute_total_score  # noqa: E402

INSTANCE_DIR = '/app/instances'
SOLUTION_DIR = '/app/solutions'
MAX_COST_PER_INSTANCE = 6.0
MAX_OVERALL_SCORE = 5.0

INSTANCE_IDS = list(range(5))


# ── helpers ──────────────────────────────────────────────────────────

def _load_instance(inst_id):
    path = os.path.join(INSTANCE_DIR, f'instance_{inst_id}.json')
    with open(path) as f:
        return json.load(f)


def _load_solution(inst_id):
    path = os.path.join(SOLUTION_DIR, f'solution_{inst_id}.json')
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


# ── per-instance tests ──────────────────────────────────────────────

@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_solution_file_exists(inst_id):
    """Solution JSON must exist for every instance."""
    sol = _load_solution(inst_id)
    assert sol is not None, f'Missing /app/solutions/solution_{inst_id}.json'


@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_solution_block_count(inst_id):
    """Number of position tuples must equal the instance block count."""
    inst = _load_instance(inst_id)
    sol = _load_solution(inst_id)
    assert sol is not None
    assert len(sol['positions']) == inst['block_count'], (
        f'Instance {inst_id}: expected {inst["block_count"]} positions, '
        f'got {len(sol["positions"])}'
    )


@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_positions_format(inst_id):
    """Each position must be a 4-element list of non-negative numbers."""
    sol = _load_solution(inst_id)
    assert sol is not None
    for i, pos in enumerate(sol['positions']):
        assert len(pos) == 4, f'Block {i}: expected 4 values, got {len(pos)}'
        assert all(isinstance(v, (int, float)) for v in pos), (
            f'Block {i}: non-numeric value in {pos}')
        assert pos[2] > 0 and pos[3] > 0, (
            f'Block {i}: width/height must be positive, got w={pos[2]}, h={pos[3]}')


@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_no_overlaps(inst_id):
    """Hard constraint: zero block overlaps."""
    inst = _load_instance(inst_id)
    sol = _load_solution(inst_id)
    assert sol is not None
    positions = [tuple(p) for p in sol['positions']]
    result = evaluate_solution(inst, positions)
    assert result['overlap_violations'] == 0, (
        f'Instance {inst_id}: {result["overlap_violations"]} overlap violations')


@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_area_tolerance(inst_id):
    """Hard constraint: soft-block areas within 1% of target."""
    inst = _load_instance(inst_id)
    sol = _load_solution(inst_id)
    assert sol is not None
    positions = [tuple(p) for p in sol['positions']]
    result = evaluate_solution(inst, positions)
    assert result['area_violations'] == 0, (
        f'Instance {inst_id}: {result["area_violations"]} area tolerance violations')


@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_dimension_constraints(inst_id):
    """Hard constraint: fixed/preplaced dimensions must match targets."""
    inst = _load_instance(inst_id)
    sol = _load_solution(inst_id)
    assert sol is not None
    positions = [tuple(p) for p in sol['positions']]
    result = evaluate_solution(inst, positions)
    assert result['dimension_violations'] == 0, (
        f'Instance {inst_id}: {result["dimension_violations"]} dimension violations')


@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_feasibility(inst_id):
    """Solution must be feasible (all hard constraints satisfied)."""
    inst = _load_instance(inst_id)
    sol = _load_solution(inst_id)
    assert sol is not None
    positions = [tuple(p) for p in sol['positions']]
    result = evaluate_solution(inst, positions)
    assert result['is_feasible'], (
        f'Instance {inst_id} infeasible: '
        f'overlaps={result["overlap_violations"]}, '
        f'area_viol={result["area_violations"]}, '
        f'dim_viol={result["dimension_violations"]}')


@pytest.mark.parametrize('inst_id', INSTANCE_IDS)
def test_cost_threshold(inst_id):
    """Per-instance cost must be below MAX_COST_PER_INSTANCE."""
    inst = _load_instance(inst_id)
    sol = _load_solution(inst_id)
    assert sol is not None
    positions = [tuple(p) for p in sol['positions']]
    result = evaluate_solution(inst, positions)
    assert result['cost'] < MAX_COST_PER_INSTANCE, (
        f'Instance {inst_id}: cost={result["cost"]:.4f} >= {MAX_COST_PER_INSTANCE}')


# ── aggregate test ──────────────────────────────────────────────────

def test_overall_weighted_score():
    """Exponentially weighted overall score must be below threshold."""
    costs = []
    block_counts = []
    for inst_id in INSTANCE_IDS:
        inst = _load_instance(inst_id)
        sol = _load_solution(inst_id)
        assert sol is not None, f'Missing solution for instance {inst_id}'
        positions = [tuple(p) for p in sol['positions']]
        result = evaluate_solution(inst, positions)
        costs.append(result['cost'])
        block_counts.append(inst['block_count'])

    score = compute_total_score(costs, block_counts)
    assert score < MAX_OVERALL_SCORE, (
        f'Overall score {score:.4f} >= {MAX_OVERALL_SCORE}  '
        f'(per-instance costs: {[f"{c:.3f}" for c in costs]})')

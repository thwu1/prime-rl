"""Solve all instances, evaluate proposed solutions, and populate SQLite database."""

import json
import os
import sys
import sqlite3

sys.path.insert(0, '/app/solvers')
from mcmf import MinCostMaxFlow


def build_and_solve(instance_path):
    """Build flow network from instance JSON and compute MCMF."""
    with open(instance_path) as f:
        data = json.load(f)

    node_map = {}
    hub_in = {}
    hub_out = {}
    n = 2  # 0 = super_source, 1 = super_sink

    for s in data['sources']:
        node_map[s['id']] = n
        n += 1
    for s in data['sinks']:
        node_map[s['id']] = n
        n += 1
    for h in data.get('hubs', []):
        hub_in[h['id']] = n
        n += 1
        hub_out[h['id']] = n
        n += 1

    solver = MinCostMaxFlow(n)

    for s in data['sources']:
        solver.add_edge(0, node_map[s['id']], s['supply'], 0)
    for s in data['sinks']:
        solver.add_edge(node_map[s['id']], 1, s['demand'], 0)
    for h in data.get('hubs', []):
        solver.add_edge(hub_in[h['id']], hub_out[h['id']], h['capacity'], 0)
    for e in data['edges']:
        frm = hub_out.get(e['from'], node_map.get(e['from']))
        to = hub_in.get(e['to'], node_map.get(e['to']))
        solver.add_edge(frm, to, e['capacity'], e['cost'])

    return solver.solve(0, 1)


def evaluate_proposed(instance_path, proposed_path):
    """Evaluate a proposed flow solution for feasibility and cost."""
    with open(instance_path) as f:
        inst = json.load(f)
    with open(proposed_path) as f:
        prop = json.load(f)

    edge_lookup = {}
    for e in inst['edges']:
        edge_lookup[(e['from'], e['to'])] = e

    hub_caps = {}
    for h in inst.get('hubs', []):
        hub_caps[h['id']] = h['capacity']

    node_out = {}
    node_in = {}
    total_cost = 0
    feasible = True

    for ef in prop['edge_flows']:
        fr, to, fl = ef['from'], ef['to'], ef['flow']
        edge = edge_lookup.get((fr, to))
        if edge is None or fl > edge['capacity'] or fl < 0:
            feasible = False
        node_out[fr] = node_out.get(fr, 0) + fl
        node_in[to] = node_in.get(to, 0) + fl
        if edge:
            total_cost += fl * edge['cost']

    for s in inst['sources']:
        if node_out.get(s['id'], 0) > s['supply']:
            feasible = False
    for s in inst['sinks']:
        if node_in.get(s['id'], 0) > s['demand']:
            feasible = False
    for h in inst.get('hubs', []):
        if node_in.get(h['id'], 0) > h['capacity']:
            feasible = False

    total_flow = sum(node_in.get(s['id'], 0) for s in inst['sinks'])
    return total_flow, total_cost, feasible


def main():
    instances_dir = '/app/instances'
    proposed_dir = '/app/proposed'
    results_dir = '/app/results'
    evals_dir = '/app/evaluations'

    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(evals_dir, exist_ok=True)

    results = {}
    evals = {}

    for fname in sorted(os.listdir(instances_dir)):
        if not fname.endswith('.json'):
            continue
        name = fname[:-5]
        inst_path = os.path.join(instances_dir, fname)

        flow, cost = build_and_solve(inst_path)
        results[name] = (flow, cost)

        with open(os.path.join(results_dir, f'{name}.txt'), 'w') as f:
            f.write(f'{flow} {cost}\n')

        prop_path = os.path.join(proposed_dir, fname)
        if os.path.exists(prop_path):
            p_flow, p_cost, feasible = evaluate_proposed(inst_path, prop_path)
            is_optimal = feasible and p_cost == cost and p_flow == flow
            cost_gap = p_cost - cost if feasible else 0

            eval_data = {
                'instance': name,
                'feasible': feasible,
                'optimal_flow': flow,
                'optimal_cost': cost,
                'proposed_flow': p_flow,
                'proposed_cost': p_cost,
                'is_optimal': is_optimal,
                'cost_gap': cost_gap
            }
            evals[name] = eval_data

            with open(os.path.join(evals_dir, f'{name}.json'), 'w') as f:
                json.dump(eval_data, f, indent=2)

    # Populate SQLite database
    db_path = '/app/results.db'
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)

    with open('/app/schema.sql') as f:
        conn.executescript(f.read())

    with open('/app/instance_summary.json') as f:
        summaries = json.load(f)

    for s in summaries:
        conn.execute(
            'INSERT INTO instances VALUES (?, ?, ?, ?, ?, ?, ?)',
            (s['name'], s['num_sources'], s['num_sinks'], s['num_hubs'],
             s['num_edges'], s['total_supply'], s['total_demand'])
        )

    for name, (flow, cost) in results.items():
        conn.execute(
            'INSERT INTO optimal_solutions VALUES (?, ?, ?)',
            (name, flow, cost)
        )

    for name, ev in evals.items():
        conn.execute(
            'INSERT INTO evaluations VALUES (?, ?, ?, ?, ?, ?)',
            (name, ev['proposed_flow'], ev['proposed_cost'],
             1 if ev['feasible'] else 0,
             1 if ev['is_optimal'] else 0,
             ev['cost_gap'])
        )

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()

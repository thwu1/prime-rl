"""
Solve script: writes correct implementations of QueryEngine methods and
graph analysis functions to /app/causal_lib/.
"""

QUERY_ENGINE_CODE = '''\
import numpy as np


class QueryEngine:
    """Evaluates causal queries on Structural Causal Models."""

    def __init__(self, n_samples=100000):
        self.n_samples = n_samples

    def evaluate_ate(self, scm, treatment_var_name, outcome_var_name,
                     t1_val, t0_val):
        """Compute ATE = E[Y | do(T=t1)] - E[Y | do(T=t0)]."""
        scm.n_samples = self.n_samples
        scm.reset_values(reset_noise=True)
        scm.sample_noise()

        # do(T = t1)
        scm.do_intervention(treatment_var_name, t1_val)
        scm.compute_all()
        y_t1 = scm.variables[outcome_var_name].value.copy()
        scm.remove_intervention(treatment_var_name)

        # do(T = t0) with the SAME noise
        scm.reset_values(reset_noise=False)
        scm.do_intervention(treatment_var_name, t0_val)
        scm.compute_all()
        y_t0 = scm.variables[outcome_var_name].value.copy()
        scm.remove_intervention(treatment_var_name)

        return float(np.nanmean(y_t1) - np.nanmean(y_t0))

    def evaluate_ctf_te(self, scm, treatment_var_name, outcome_var_name,
                        factual_var_names, factual_vals,
                        t1_val, t0_val, target_y_val=None):
        """Compute Ctf-TE via abduction-action-prediction."""
        # --- Step 1: Abduction ---
        scm.n_samples = self.n_samples
        scm.reset_values(reset_noise=True)
        scm.sample_noise()
        scm.compute_all()

        # Build mask for factual condition
        mask = np.ones(self.n_samples, dtype=bool)
        for var_name, val in zip(factual_var_names, factual_vals):
            var_values = scm.variables[var_name].value.flatten()
            mask &= (var_values == val)

        if not np.any(mask):
            return float("nan")

        # Store exogenous realizations for matching observations
        exogenous_realizations = {}
        for noise_name in scm.noise_var_names:
            exogenous_realizations[noise_name] = (
                scm.variables[noise_name].value[mask].copy()
            )

        n_matched = int(np.sum(mask))

        # --- Step 2: Action + Prediction under do(T = t1) ---
        scm.n_samples = n_matched

        for noise_name, vals in exogenous_realizations.items():
            scm.variables[noise_name].value = vals.copy()

        scm.reset_values(reset_noise=False)
        scm.do_intervention(treatment_var_name, t1_val)
        scm.compute_all()
        y_t1 = scm.variables[outcome_var_name].value.copy()
        scm.remove_intervention(treatment_var_name)

        # --- Step 3: Action + Prediction under do(T = t0) ---
        for noise_name, vals in exogenous_realizations.items():
            scm.variables[noise_name].value = vals.copy()

        scm.reset_values(reset_noise=False)
        scm.do_intervention(treatment_var_name, t0_val)
        scm.compute_all()
        y_t0 = scm.variables[outcome_var_name].value.copy()
        scm.remove_intervention(treatment_var_name)

        # --- Step 4: Compute effect ---
        if target_y_val is not None:
            p1 = float(np.mean(y_t1.flatten() == target_y_val))
            p0 = float(np.mean(y_t0.flatten() == target_y_val))
        else:
            p1 = float(np.mean(y_t1))
            p0 = float(np.mean(y_t0))

        return p1 - p0
'''

GRAPH_ANALYSIS_CODE = '''\
"""Graph analysis utilities for Structural Causal Models."""

from collections import deque
from itertools import combinations


def build_mutilated_graph(scm, remove_incoming_to=None, remove_outgoing_from=None):
    """Construct a mutilated DAG over endogenous variables only."""
    remove_in = set(remove_incoming_to or [])
    remove_out = set(remove_outgoing_from or [])

    endogenous = [
        name for name in scm.variables if not scm.variables[name].exogenous
    ]
    adj = {name: [] for name in endogenous}

    for name in endogenous:
        for child in scm.children.get(name, []):
            child_var = scm.variables.get(child)
            if child_var is None or child_var.exogenous:
                continue
            if name in remove_out:
                continue
            if child in remove_in:
                continue
            adj[name].append(child)

    return adj


def is_d_separated(adj_dict, x_nodes, y_nodes, z_nodes):
    """Test d-separation using the Bayes-Ball algorithm."""
    x_nodes = set(x_nodes)
    y_nodes = set(y_nodes)
    z_nodes = set(z_nodes)

    all_nodes = set(adj_dict.keys())
    for children in adj_dict.values():
        for c in children:
            all_nodes.add(c)
    parent_map = {n: set() for n in all_nodes}
    for p, children in adj_dict.items():
        for c in children:
            parent_map[c].add(p)

    # Pre-compute ancestors of Z
    ancestors_of_z = set()
    for z in z_nodes:
        stack = [z]
        while stack:
            n = stack.pop()
            if n in ancestors_of_z:
                continue
            ancestors_of_z.add(n)
            for p in parent_map.get(n, set()):
                stack.append(p)

    visited = set()
    queue = deque()

    for x in x_nodes:
        queue.append((x, True))
        queue.append((x, False))

    while queue:
        node, from_child = queue.popleft()
        if (node, from_child) in visited:
            continue
        visited.add((node, from_child))

        if node in y_nodes:
            return False

        if from_child:
            if node not in z_nodes:
                for p in parent_map.get(node, set()):
                    queue.append((p, True))
                for c in adj_dict.get(node, []):
                    queue.append((c, False))
        else:
            if node not in z_nodes:
                for c in adj_dict.get(node, []):
                    queue.append((c, False))
            if node in ancestors_of_z:
                for p in parent_map.get(node, set()):
                    queue.append((p, True))

    return True


def extract_latent_projection(scm):
    """Project hidden variables to produce an ADMG."""
    topo = scm.topological_sort()
    visible_names = [n for n in topo if scm.variables[n].visible]
    visible_set = set(visible_names)

    directed = {n: set() for n in visible_names}
    bidirected = set()

    def find_visible_ancestors(var_name, result):
        for p in scm.parents.get(var_name, []):
            if p in visible_set:
                result.add(p)
            else:
                find_visible_ancestors(p, result)

    def find_visible_descendants(var_name, result):
        for c in scm.children.get(var_name, []):
            if c in visible_set:
                result.add(c)
            else:
                find_visible_descendants(c, result)

    for v in visible_names:
        for c in scm.children.get(v, []):
            if c in visible_set:
                directed[v].add(c)

    non_visible = [n for n in topo if not scm.variables[n].visible]
    for nv in non_visible:
        vis_parents = set()
        find_visible_ancestors(nv, vis_parents)
        vis_descendants = set()
        find_visible_descendants(nv, vis_descendants)

        for p in vis_parents:
            for d in vis_descendants:
                directed[p].add(d)

        desc_list = sorted(vis_descendants)
        for i in range(len(desc_list)):
            for j in range(i + 1, len(desc_list)):
                bidirected.add(frozenset({desc_list[i], desc_list[j]}))

    return directed, bidirected, visible_names


def find_backdoor_adjustment(adj_dict, treatment, outcome, hidden_vars=None):
    """Find a valid back-door adjustment set among visible variables."""
    hidden = set(hidden_vars or [])
    all_nodes = set(adj_dict.keys())

    descendants = set()
    stack = list(adj_dict.get(treatment, []))
    while stack:
        n = stack.pop()
        if n not in descendants:
            descendants.add(n)
            stack.extend(adj_dict.get(n, []))

    candidates = sorted(all_nodes - {treatment, outcome} - hidden - descendants)

    g_underline = {node: list(adj_dict.get(node, [])) for node in all_nodes}
    g_underline[treatment] = []

    for size in range(len(candidates) + 1):
        for subset in combinations(candidates, size):
            z = set(subset)
            if is_d_separated(g_underline, {treatment}, {outcome}, z):
                return frozenset(z)

    return None
'''

import os

with open("/app/causal_lib/query_engine.py", "w") as f:
    f.write(QUERY_ENGINE_CODE)

with open("/app/causal_lib/graph_analysis.py", "w") as f:
    f.write(GRAPH_ANALYSIS_CODE)

print("Implementations written to /app/causal_lib/")

#!/usr/bin/env python3

"""Solution: implement is_d_separated, verify_rule2, compute_counterfactual_te."""

import os
import subprocess


# ─── 1. Implement is_d_separated in graph_utils.py ──────────────────

GRAPH_UTILS = '''\

"""Graph utilities for causal inference on directed acyclic graphs."""

from collections import defaultdict, deque


def is_d_separated(parents_map, X_set, Y_set, Z_set):
    """Determine whether X_set and Y_set are d-separated given Z_set
    in the DAG defined by parents_map.

    Uses the Bayes Ball algorithm. A BFS traversal tracks states
    (node, direction) where direction indicates how the ball arrived:
    - "up": arrived from a child (traveling toward parents)
    - "down": arrived from a parent (traveling toward children)

    Transition rules:
    - Arriving UP at a non-evidence node: propagate UP to parents
      and DOWN to children (fork/chain pattern).
    - Arriving DOWN at a non-evidence node: propagate DOWN to children
      only (chain pattern, non-collider passthrough).
    - Arriving DOWN at an evidence node: propagate UP to parents
      (collider activated by conditioning — explaining away).
    - Arriving UP at an evidence node: blocked (non-collider in Z).

    Collider activation through descendants is handled naturally:
    the ball can travel DOWN to a descendant in Z, then back UP
    through the collider.

    Args:
        parents_map: dict mapping each node name to a list of parent names.
        X_set: set of source node names.
        Y_set: set of target node names.
        Z_set: set of conditioning node names.

    Returns:
        True if d-separated (no active path), False otherwise.
    """
    # Build children map from parents map
    children_map = defaultdict(list)
    for node, parents in parents_map.items():
        for p in parents:
            children_map[p].append(node)

    visited = set()
    queue = deque()

    # Initialize: send ball "up" from each source node
    for x in X_set:
        queue.append((x, "up"))

    while queue:
        node, direction = queue.popleft()
        if (node, direction) in visited:
            continue
        visited.add((node, direction))

        # Check if we reached a target node
        if node in Y_set:
            return False

        if direction == "up" and node not in Z_set:
            # Non-evidence node, arrived from child
            # Fork/chain: propagate to parents and children
            for parent in parents_map.get(node, []):
                if (parent, "up") not in visited:
                    queue.append((parent, "up"))
            for child in children_map.get(node, []):
                if (child, "down") not in visited:
                    queue.append((child, "down"))

        elif direction == "down" and node not in Z_set:
            # Non-evidence node, arrived from parent
            # Chain: propagate to children only
            for child in children_map.get(node, []):
                if (child, "down") not in visited:
                    queue.append((child, "down"))

        elif direction == "down" and node in Z_set:
            # Evidence node, arrived from parent
            # Collider activated: propagate up to parents
            for parent in parents_map.get(node, []):
                if (parent, "up") not in visited:
                    queue.append((parent, "up"))

        # direction == "up" and node in Z_set: blocked (non-collider in Z)

    return True


def compute_latent_projection(parents_map, children_map, hidden_vars, all_vars):
    """Compute the latent projection of a DAG onto its visible variables.

    When hidden (latent) variables are removed from the graph, any pair of
    visible variables that share a hidden common ancestor become connected
    by a bidirectional edge, representing unobserved confounding.

    Args:
        parents_map: dict mapping node -> list of parent names.
        children_map: dict mapping node -> list of child names.
        hidden_vars: set of hidden (latent) variable names to project out.
        all_vars: set of all variable names in the graph.

    Returns:
        A tuple (visible_parents, bidirectional_edges) where:
        - visible_parents: dict mapping each visible node to a list of its
          visible parents (directed edges that remain).
        - bidirectional_edges: set of frozenset({A, B}) pairs representing
          unobserved confounding between visible variables.
    """
    visible = all_vars - hidden_vars

    visible_parents = {}
    for v in visible:
        visible_parents[v] = [p for p in parents_map.get(v, []) if p in visible]

    bidirectional = set()
    for h in hidden_vars:
        visible_children = [c for c in children_map.get(h, []) if c in visible]
        for i in range(len(visible_children)):
            for j in range(i + 1, len(visible_children)):
                bidirectional.add(
                    frozenset({visible_children[i], visible_children[j]})
                )

    return visible_parents, bidirectional
'''


# ─── 2. Implement verify_rule2 in do_calculus.py ────────────────────

DO_CALCULUS = '''\

"""Do-calculus verification for Pearl\'s causal inference rules."""

from graph_utils import is_d_separated


def verify_rule2(parents_map, X_vars, Z_vars, Y_vars, W_vars):
    """Verify Pearl\'s do-calculus Rule 2 (Action/Observation Exchange).

    Rule 2 states that under certain graphical conditions, an intervention
    do(Z=z) can be replaced by a mere observation Z=z:

        P(y | do(x), do(z), w) = P(y | do(x), z, w)

    The condition for Rule 2 to hold is:

        (Y _|_ Z | X u W)  in  G_{X_bar, Z_underline}

    where the mutilated graph G_{X_bar, Z_underline} is obtained from the
    original DAG by:
      - Removing all edges INCOMING to nodes in X  (the "X-bar" operation)
      - Removing all edges OUTGOING from nodes in Z  (the "Z-underline" operation)

    Args:
        parents_map: dict mapping each node to its list of parents.
        X_vars: set of intervention variables (incoming edges removed).
        Z_vars: set of variables whose do/observe status is being tested.
        Y_vars: set of outcome variables.
        W_vars: set of additional conditioning (observed) variables.

    Returns:
        True if the d-separation condition holds in the mutilated graph
        (i.e., Rule 2 is applicable), False otherwise.
    """
    # Construct the mutilated graph G_{X_bar, Z_underline}
    mutilated_parents = {}
    for node, parents in parents_map.items():
        if node in X_vars:
            # X_bar: remove all incoming edges to X nodes
            mutilated_parents[node] = []
        else:
            # Z_underline: remove all outgoing edges from Z nodes
            # (i.e., remove Z nodes from parent lists of other nodes)
            mutilated_parents[node] = [p for p in parents if p not in Z_vars]

    # Check d-separation: (Y _|_ Z | X u W) in G_{X_bar, Z_underline}
    conditioning = X_vars | W_vars
    return is_d_separated(mutilated_parents, Y_vars, Z_vars, conditioning)
'''


# ─── 3. Implement compute_counterfactual_te in query_engine.py ──────

QUERY_ENGINE = '''\

"""Query engine for causal inference computations on SCMs."""

import numpy as np


def compute_ate(scm, treatment, outcome, t1_val, t0_val, n_samples=100000):
    """Compute the Average Treatment Effect: E[Y|do(T=t1)] - E[Y|do(T=t0)].

    Uses Monte Carlo estimation by sampling from interventional distributions.

    Args:
        scm: SCM object with mechanisms and noise distributions configured.
        treatment: Name of the treatment variable.
        outcome: Name of the outcome variable.
        t1_val: Treatment value for the first intervention.
        t0_val: Treatment value for the second (baseline) intervention.
        n_samples: Number of Monte Carlo samples.

    Returns:
        float: Estimated ATE.
    """
    scm.n_samples = n_samples

    # E[Y | do(T = t1)]
    scm.reset_values()
    scm.sample_noise()
    scm.do_intervention(treatment, t1_val)
    scm.forward()
    y_t1 = scm.variables[outcome].value.copy()
    scm.remove_intervention(treatment)

    # E[Y | do(T = t0)] -- reuse same noise for variance reduction
    scm.reset_values(reset_noise=False)
    scm.do_intervention(treatment, t0_val)
    scm.forward()
    y_t0 = scm.variables[outcome].value.copy()
    scm.remove_intervention(treatment)

    return float(np.mean(y_t1 - y_t0))


def compute_counterfactual_te(scm, treatment, outcome, t1_val, t0_val,
                               condition_vars, condition_vals,
                               n_samples=200000, tolerance=0.5):
    """Compute the Counterfactual Treatment Effect (CTF-TE):
    E[Y_{do(T=t1)} - Y_{do(T=t0)} | condition_vars = condition_vals]

    This implements Pearl\'s three-step counterfactual procedure:

    1. **Abduction** -- Sample from the observational (pre-intervention)
       distribution and identify samples consistent with the observed
       evidence (the conditioning). The exogenous noise values for these
       samples constitute the "abducted" noise.

    2. **Action** -- Modify the SCM by applying the desired hard
       intervention do(T = value).

    3. **Prediction** -- Forward-compute the outcome variable using the
       modified SCM and the abducted (fixed) noise values.

    For continuous conditioning variables, exact matching is replaced by
    retaining samples within ``tolerance`` of the target value.

    Args:
        scm: SCM object with mechanisms and noise distributions configured.
        treatment: Name of the treatment variable.
        outcome: Name of the outcome variable.
        t1_val: Treatment value in the first (treatment) world.
        t0_val: Treatment value in the second (control) world.
        condition_vars: List of variable names to condition on.
        condition_vals: List of target values for those variables.
        n_samples: Number of Monte Carlo samples for estimation.
        tolerance: Window half-width for matching continuous conditions.

    Returns:
        float: Estimated E[Y_{do(T=t1)} - Y_{do(T=t0)} | conditions].
    """
    # Step 1: ABDUCTION -- sample observational data and find matching samples
    scm.n_samples = n_samples
    scm.reset_values()
    scm.sample_noise()
    scm.forward()

    # Find samples matching the conditioning evidence (within tolerance)
    mask = np.ones(n_samples, dtype=bool)
    for var_name, target_val in zip(condition_vars, condition_vals):
        var_vals = scm.variables[var_name].value
        diff = np.abs(var_vals - target_val)
        if diff.ndim > 1:
            mask &= np.all(diff < tolerance, axis=1)
        else:
            mask &= diff < tolerance

    n_match = int(np.sum(mask))
    if n_match == 0:
        return float(\'nan\')

    # Store the abducted exogenous noise for matching samples
    abducted_noise = {}
    for var_name, u_var in scm.noise_vars.items():
        abducted_noise[var_name] = u_var.value[mask].copy()

    # Step 2 & 3: ACTION + PREDICTION for treatment world (do(T = t1))
    scm.n_samples = n_match

    # Restore abducted noise
    for var_name, u_var in scm.noise_vars.items():
        u_var.value = abducted_noise[var_name]

    scm.reset_values(reset_noise=False)
    scm.do_intervention(treatment, t1_val)
    scm.forward()
    y_t1 = scm.variables[outcome].value.copy()
    scm.remove_intervention(treatment)

    # Step 2 & 3: ACTION + PREDICTION for control world (do(T = t0))
    # Restore abducted noise again
    for var_name, u_var in scm.noise_vars.items():
        u_var.value = abducted_noise[var_name]

    scm.reset_values(reset_noise=False)
    scm.do_intervention(treatment, t0_val)
    scm.forward()
    y_t0 = scm.variables[outcome].value.copy()
    scm.remove_intervention(treatment)

    # Restore original n_samples
    scm.n_samples = n_samples

    return float(np.mean(y_t1 - y_t0))
'''


# ─── Apply all fixes ────────────────────────────────────────────────

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  Wrote: {path}")


print("Implementing causal analysis functions...")
write_file("/app/graph_utils.py", GRAPH_UTILS)
write_file("/app/do_calculus.py", DO_CALCULUS)
write_file("/app/query_engine.py", QUERY_ENGINE)

# Remove stale output
if os.path.exists("/app/output"):
    import shutil
    shutil.rmtree("/app/output", ignore_errors=True)

print("Running analysis pipeline...")
result = subprocess.run(
    ["bash", "/app/run_analysis.sh"],
    capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print(result.stderr)
if result.returncode != 0:
    print(f"Pipeline exited with code {result.returncode}")
    raise SystemExit(result.returncode)
print("Done.")

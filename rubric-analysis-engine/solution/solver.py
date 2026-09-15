#!/usr/bin/env python3
"""Correct rubric scoring pipeline — reference solution."""

import sqlite3
import json
import os
import yaml

DB_PATH = "/app/data/rubrics.db"
POLICY_PATH = "/app/config/policy.yaml"
OUTPUT = "/app/output"


def get_db():
    return sqlite3.connect(DB_PATH)


def load_policy():
    with open(POLICY_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Tree reconstruction from adjacency list
# ---------------------------------------------------------------------------

def build_tree(conn, rubric_name):
    """Build a tree dict from the adjacency-list rubric_nodes table."""
    rows = conn.execute(
        "SELECT node_id, parent_id, weight, task_category "
        "FROM rubric_nodes WHERE rubric_name = ?",
        (rubric_name,),
    ).fetchall()

    nodes = {}
    for nid, pid, w, cat in rows:
        nodes[nid] = {
            "id": nid,
            "parent_id": pid,
            "weight": w,
            "task_category": cat,
            "children": [],
        }

    root = None
    for nid, node in nodes.items():
        pid = node["parent_id"]
        if pid is None:
            root = node
        else:
            nodes[pid]["children"].append(node)

    return root


def get_leaves(node):
    """Return all leaf nodes (those with no children)."""
    if not node["children"]:
        return [node]
    leaves = []
    for ch in node["children"]:
        leaves.extend(get_leaves(ch))
    return leaves


# ---------------------------------------------------------------------------
# Hierarchical weighted score
# ---------------------------------------------------------------------------

def compute_score(node, grading):
    """Recursive weighted-average score propagation."""
    if not node["children"]:
        return float(grading.get(node["id"], 0))
    total_w = sum(ch["weight"] for ch in node["children"])
    return sum(
        ch["weight"] * compute_score(ch, grading) for ch in node["children"]
    ) / total_w


# ---------------------------------------------------------------------------
# Effective weights
# ---------------------------------------------------------------------------

def compute_effective_weights(node, parent_ew=1.0):
    """Product of normalized weight ratios along root-to-leaf path."""
    if not node["children"]:
        return {node["id"]: parent_ew}
    total_w = sum(ch["weight"] for ch in node["children"])
    result = {}
    for ch in node["children"]:
        child_ew = parent_ew * ch["weight"] / total_w
        result.update(compute_effective_weights(ch, child_ew))
    return result


# ---------------------------------------------------------------------------
# Category analysis
# ---------------------------------------------------------------------------

def compute_categories(tree, grading):
    ew = compute_effective_weights(tree)
    leaves = get_leaves(tree)
    cats = {}
    for leaf in leaves:
        cat = leaf["task_category"]
        if cat not in cats:
            cats[cat] = {"ws": 0.0, "tw": 0.0}
        w = ew[leaf["id"]]
        s = float(grading.get(leaf["id"], 0))
        cats[cat]["ws"] += w * s
        cats[cat]["tw"] += w
    result = {}
    for cat in sorted(cats):
        c = cats[cat]
        result[cat] = round(c["ws"] / c["tw"], 6) if c["tw"] > 0 else 0.0
    return result


# ---------------------------------------------------------------------------
# Agreement metrics (weighted by effective weights)
# ---------------------------------------------------------------------------

def compute_weighted_agreement(leaves, ew, g1, g2):
    """Agreement metrics weighted by effective leaf weights."""
    wtp = wfp = wfn = wtn = 0.0
    for leaf in leaves:
        nid = leaf["id"]
        w = ew[nid]
        pred, ref = g1.get(nid, 0), g2.get(nid, 0)
        if pred == 1 and ref == 1:
            wtp += w
        elif pred == 1 and ref == 0:
            wfp += w
        elif pred == 0 and ref == 1:
            wfn += w
        else:
            wtn += w

    total = wtp + wfp + wfn + wtn
    acc = (wtp + wtn) / total if total > 0 else 0.0
    prec = wtp / (wtp + wfp) if (wtp + wfp) > 0 else 0.0
    rec = wtp / (wtp + wfn) if (wtp + wfn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    p_o = acc
    p_pred1 = (wtp + wfp) / total if total > 0 else 0.0
    p_ref1 = (wtp + wfn) / total if total > 0 else 0.0
    p_e = p_pred1 * p_ref1 + (1 - p_pred1) * (1 - p_ref1)
    kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) != 0 else 1.0

    return {
        "cohens_kappa": round(kappa, 6),
        "accuracy": round(acc, 6),
        "precision": round(prec, 6),
        "recall": round(rec, 6),
        "f1": round(f1, 6),
    }


def compute_unweighted_agreement(leaves, g1, g2):
    """Standard unweighted agreement metrics."""
    tp = fp = fn = tn = 0
    for leaf in leaves:
        nid = leaf["id"]
        pred, ref = g1.get(nid, 0), g2.get(nid, 0)
        if pred == 1 and ref == 1:
            tp += 1
        elif pred == 1 and ref == 0:
            fp += 1
        elif pred == 0 and ref == 1:
            fn += 1
        else:
            tn += 1

    n = tp + fp + fn + tn
    acc = (tp + tn) / n if n > 0 else 0.0
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    p_o = acc
    p_pred1 = (tp + fp) / n if n > 0 else 0.0
    p_ref1 = (tp + fn) / n if n > 0 else 0.0
    p_e = p_pred1 * p_ref1 + (1 - p_pred1) * (1 - p_ref1)
    kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) != 0 else 1.0

    return {
        "cohens_kappa": round(kappa, 6),
        "accuracy": round(acc, 6),
        "precision": round(prec, 6),
        "recall": round(rec, 6),
        "f1": round(f1, 6),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT, exist_ok=True)
    conn = get_db()
    policy = load_policy()
    use_weighted_agreement = policy.get("agreement", {}).get("weighted", False)

    # Discover all rubric names
    rubric_names = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT rubric_name FROM rubric_nodes"
        ).fetchall()
    ]

    # Discover all rubric/grading pairs
    rg_pairs = conn.execute(
        "SELECT DISTINCT rubric_name, grading_id FROM gradings"
    ).fetchall()

    # Build trees
    trees = {rn: build_tree(conn, rn) for rn in rubric_names}

    # Load all gradings
    all_gradings = {}
    for rn, gid in rg_pairs:
        scores = dict(
            conn.execute(
                "SELECT node_id, score FROM gradings WHERE grading_id = ?",
                (gid,),
            ).fetchall()
        )
        all_gradings[(rn, gid)] = scores

    # 1. Scores
    scores_out = {}
    for rn, gid in rg_pairs:
        key = f"{rn}/{gid}"
        scores_out[key] = round(compute_score(trees[rn], all_gradings[(rn, gid)]), 6)
    with open(os.path.join(OUTPUT, "scores.json"), "w") as f:
        json.dump(scores_out, f, indent=2)

    # 2. Sensitivity
    sens_out = {}
    for rn in rubric_names:
        ew = compute_effective_weights(trees[rn])
        sorted_items = sorted(ew.items(), key=lambda x: (-round(x[1], 9), x[0]))
        sens_out[rn] = {k: round(v, 6) for k, v in sorted_items}
    with open(os.path.join(OUTPUT, "sensitivity.json"), "w") as f:
        json.dump(sens_out, f, indent=2)

    # 3. Categories
    cats_out = {}
    for rn, gid in rg_pairs:
        key = f"{rn}/{gid}"
        cats_out[key] = compute_categories(trees[rn], all_gradings[(rn, gid)])
    with open(os.path.join(OUTPUT, "categories.json"), "w") as f:
        json.dump(cats_out, f, indent=2)

    # 4. Agreement
    agree_out = {}
    pairs = conn.execute(
        "SELECT pair_id, rubric_name, grading_id_1, grading_id_2 "
        "FROM agreement_pairs"
    ).fetchall()
    for pid, rn, gid1, gid2 in pairs:
        leaves = get_leaves(trees[rn])
        g1 = all_gradings[(rn, gid1)]
        g2 = all_gradings[(rn, gid2)]
        if use_weighted_agreement:
            ew = compute_effective_weights(trees[rn])
            agree_out[pid] = compute_weighted_agreement(leaves, ew, g1, g2)
        else:
            agree_out[pid] = compute_unweighted_agreement(leaves, g1, g2)
    with open(os.path.join(OUTPUT, "agreement.json"), "w") as f:
        json.dump(agree_out, f, indent=2)

    # 5. Improvements
    improv_out = {}
    for rn, gid in rg_pairs:
        key = f"{rn}/{gid}"
        grading = all_gradings[(rn, gid)]
        root_score = scores_out[key]
        if root_score >= 1.0 - 1e-9:
            continue
        ew = compute_effective_weights(trees[rn])
        unsatisfied = [
            (nid, w) for nid, w in ew.items() if grading.get(nid, 0) == 0
        ]
        unsatisfied.sort(key=lambda x: (-round(x[1], 9), x[0]))
        k = min(3, len(unsatisfied))
        selected = unsatisfied[:k]
        top_leaves = [nid for nid, _ in selected]
        improved = root_score + sum(w for _, w in selected)
        improv_out[key] = {
            "top_leaves": top_leaves,
            "improved_score": round(improved, 6),
        }
    with open(os.path.join(OUTPUT, "improvements.json"), "w") as f:
        json.dump(improv_out, f, indent=2)

    print("All output files written to", OUTPUT)


if __name__ == "__main__":
    main()

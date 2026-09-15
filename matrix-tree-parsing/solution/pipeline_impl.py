"""Pipeline driver: reads instances from SQLite, computes arborescence
distribution properties, writes results to database, renders visualizations."""

import sqlite3
import subprocess
import os
import sys
import numpy as np

sys.path.insert(0, '/app')
from arborescence import (log_partition, arc_marginals, entropy,
                           map_tree, expected_attachment_score, kl_divergence)

DB_PATH = '/app/data/treebank.db'
OUTPUT_DIR = '/app/output'


def load_all_instances():
    """Read all instances from the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, n FROM instances")
    instances = {}
    for inst_id, n in c.fetchall():
        scores = np.zeros((n + 1, n + 1))
        c.execute(
            "SELECT head_node, dep_node, score FROM arc_scores WHERE instance_id = ?",
            (inst_id,)
        )
        for h, d, s in c.fetchall():
            scores[h][d] = s

        gold = [-1] * (n + 1)
        c.execute(
            "SELECT node, head_node FROM gold_heads WHERE instance_id = ?",
            (inst_id,)
        )
        for node, head in c.fetchall():
            gold[node] = head

        instances[inst_id] = {'n': n, 'scores': scores, 'gold_heads': gold}

    conn.close()
    return instances


def render_map_tree(inst_id, heads, scores, n):
    """Generate DOT file and render to SVG via graphviz."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    dot_path = os.path.join(OUTPUT_DIR, f'{inst_id}_map.dot')
    svg_path = os.path.join(OUTPUT_DIR, f'{inst_id}_map.svg')

    lines = [f'digraph {inst_id} {{']
    lines.append('  rankdir=TB;')
    lines.append('  node [shape=circle];')
    for j in range(n + 1):
        lines.append(f'  n{j} [label="{j}"];')
    for j in range(1, n + 1):
        h = int(heads[j])
        s = float(scores[h][j])
        lines.append(f'  n{h} -> n{j} [label="{s:.4f}"];')
    lines.append('}')

    with open(dot_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    subprocess.run(['dot', '-Tsvg', '-o', svg_path, dot_path], check=True)
    print(f"  Rendered {svg_path}")


def main():
    instances = load_all_instances()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create output tables
    c.execute(
        "CREATE TABLE IF NOT EXISTS computed_partition "
        "(instance_id TEXT PRIMARY KEY, log_z REAL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS computed_entropy "
        "(instance_id TEXT PRIMARY KEY, entropy_nats REAL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS computed_map_heads "
        "(instance_id TEXT, node INTEGER, head INTEGER, "
        "PRIMARY KEY (instance_id, node))"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS computed_eas "
        "(instance_id TEXT PRIMARY KEY, score REAL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS computed_kl "
        "(instance_id_p TEXT, instance_id_q TEXT, kl_value REAL, "
        "PRIMARY KEY (instance_id_p, instance_id_q))"
    )

    # Per-instance computations
    for inst_id, inst in instances.items():
        scores = inst['scores']
        n = inst['n']
        gold = inst['gold_heads']

        lz = log_partition(scores)
        ent = entropy(scores)
        heads = map_tree(scores)
        eas = expected_attachment_score(scores, gold)

        c.execute("INSERT OR REPLACE INTO computed_partition VALUES (?, ?)",
                  (inst_id, float(lz)))
        c.execute("INSERT OR REPLACE INTO computed_entropy VALUES (?, ?)",
                  (inst_id, float(ent)))
        for j in range(1, n + 1):
            c.execute("INSERT OR REPLACE INTO computed_map_heads VALUES (?, ?, ?)",
                      (inst_id, j, int(heads[j])))
        c.execute("INSERT OR REPLACE INTO computed_eas VALUES (?, ?)",
                  (inst_id, float(eas)))

        render_map_tree(inst_id, heads, scores, n)
        print(f"{inst_id} (n={n}): log_z={lz:.6f} entropy={ent:.6f} eas={eas:.6f}")

    # KL between all ordered pairs of instances with the same n
    by_n = {}
    for inst_id, inst in instances.items():
        by_n.setdefault(inst['n'], []).append(inst_id)

    for n_val, ids in by_n.items():
        for p_id in ids:
            for q_id in ids:
                kl_val = kl_divergence(
                    instances[p_id]['scores'],
                    instances[q_id]['scores']
                )
                c.execute(
                    "INSERT OR REPLACE INTO computed_kl VALUES (?, ?, ?)",
                    (p_id, q_id, float(kl_val))
                )
                print(f"KL({p_id}||{q_id}) = {kl_val:.8f}")

    conn.commit()
    conn.close()
    print("Pipeline complete.")


if __name__ == '__main__':
    main()

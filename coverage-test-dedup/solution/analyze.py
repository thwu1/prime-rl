#!/usr/bin/env python3
"""Analyze Hypothesis Corpus test coverage across a multi-database SQLite setup.

Aggregates per-node coverage from companion database, estimates pairwise
similarity via MinHash, and computes a minimal coverage-preserving test set.
"""

import hashlib
import json
import random
import sqlite3

DB_PATH = "/data/corpus.db"
TC_DB_PATH = "/data/corpus_test_cases.db"
REPORT_PATH = "/app/analysis_report.json"
NUM_PERM = 128
JACCARD_THRESHOLD = 0.75
PRIME = (1 << 61) - 1  # Mersenne prime


class MinHash:
    """MinHash signature using universal hash functions h(x) = (a*x + b) % p."""

    def __init__(self, num_perm=128, seed=54321):
        self.num_perm = num_perm
        self.hashvalues = [PRIME] * num_perm
        rng = random.Random(seed)
        self._a = [rng.randint(1, PRIME - 1) for _ in range(num_perm)]
        self._b = [rng.randint(0, PRIME - 1) for _ in range(num_perm)]

    def _element_hash(self, elem):
        raw = f"{elem[0]}:{elem[1]}".encode()
        return int(hashlib.sha256(raw).hexdigest(), 16) % PRIME

    def update(self, elements):
        for e in elements:
            h = self._element_hash(e)
            for i in range(self.num_perm):
                v = (self._a[i] * h + self._b[i]) % PRIME
                if v < self.hashvalues[i]:
                    self.hashvalues[i] = v

    def jaccard(self, other):
        return sum(
            a == b for a, b in zip(self.hashvalues, other.hashvalues)
        ) / self.num_perm


def aggregate_coverage(tc_conn, node_db_id):
    """Aggregate coverage from runtime_test_case for a node.
    Only data_status IN (2, 3) — excludes overrun (0) and filtered (1)."""
    rows = tc_conn.execute(
        "SELECT coverage FROM runtime_test_case "
        "WHERE node_id = ? AND data_status IN (2, 3)",
        (node_db_id,),
    ).fetchall()
    cov_set = set()
    for row in rows:
        for fp, lines in json.loads(row[0]).items():
            for ln in lines:
                cov_set.add((fp, ln))
    return cov_set


def greedy_set_cover(node_coverages, universe):
    """Greedy approximation to minimum set cover."""
    remaining = set(universe)
    selected = []
    pool = {nid: set(cov) for nid, cov in node_coverages.items()}

    while remaining and pool:
        best = max(pool, key=lambda n: len(pool[n] & remaining))
        if not (pool[best] & remaining):
            break
        selected.append(best)
        remaining -= pool[best]
        del pool[best]

    return selected


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tc_conn = sqlite3.connect(TC_DB_PATH)

    # Only analyze valid repositories
    repos = conn.execute(
        "SELECT id, full_name FROM core_repository WHERE status = 'valid'"
    ).fetchall()
    result = {"repositories": {}}

    for repo in repos:
        repo_id, repo_name = repo["id"], repo["full_name"]

        # Only analyze nodes with status 'passed' or 'failed'
        nodes = conn.execute(
            """SELECT cn.id AS db_id, cn.node_id
               FROM core_node cn
               JOIN runtime_summary rs ON rs.node_id = cn.id
               WHERE cn.repo_id = ? AND rs.status IN ('passed', 'failed')""",
            (repo_id,),
        ).fetchall()

        if not nodes:
            continue

        # Aggregate coverage per node from companion database
        node_covs = {}
        for nd in nodes:
            cov = aggregate_coverage(tc_conn, nd["db_id"])
            node_covs[nd["node_id"]] = cov

        all_lines = set()
        for c in node_covs.values():
            all_lines |= c

        # Compute MinHash signatures
        minhashes = {}
        for nid, cov in node_covs.items():
            mh = MinHash(NUM_PERM)
            mh.update(cov)
            minhashes[nid] = mh

        # Find duplicate pairs
        nids = list(node_covs.keys())
        dup_pairs = []
        for i in range(len(nids)):
            for j in range(i + 1, len(nids)):
                est = minhashes[nids[i]].jaccard(minhashes[nids[j]])
                if est >= JACCARD_THRESHOLD:
                    dup_pairs.append({
                        "node_a": nids[i],
                        "node_b": nids[j],
                        "jaccard_estimate": round(est, 4),
                    })

        # Greedy minimal test set
        selected = greedy_set_cover(node_covs, all_lines)
        removed = [n for n in nids if n not in selected]

        result["repositories"][repo_name] = {
            "total_nodes": len(node_covs),
            "total_lines_covered": len(all_lines),
            "duplicate_pairs": dup_pairs,
            "minimal_test_set": selected,
            "minimal_set_size": len(selected),
            "removed_nodes": removed,
        }

    conn.close()
    tc_conn.close()

    with open(REPORT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()

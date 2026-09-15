"""
"""
import pytest
import numpy as np
import sqlite3
import os
import sys
import itertools

sys.path.insert(0, '/app')

DB_PATH = '/app/data/treebank.db'


def load_instance(name):
    """Load an instance from the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT n FROM instances WHERE id = ?", (name,))
    row = c.fetchone()
    assert row is not None, f"Instance {name} not found in database"
    n = row[0]

    scores = np.zeros((n + 1, n + 1))
    c.execute("SELECT head_node, dep_node, score FROM arc_scores WHERE instance_id = ?", (name,))
    for head, dep, score in c.fetchall():
        scores[head][dep] = score

    gold = [-1] * (n + 1)
    c.execute("SELECT node, head_node FROM gold_heads WHERE instance_id = ?", (name,))
    for node, head in c.fetchall():
        gold[node] = head

    conn.close()
    return {'n': n, 'scores': scores, 'gold_heads': gold}


def is_valid_arborescence(heads, n):
    """Check that heads defines a valid arborescence rooted at 0."""
    if len(heads) != n + 1:
        return False
    if int(heads[0]) != -1:
        return False
    for j in range(1, n + 1):
        h = int(heads[j])
        if h < 0 or h > n or h == j:
            return False
    for j in range(1, n + 1):
        visited = set()
        current = j
        while current != 0:
            if current in visited:
                return False
            visited.add(current)
            current = int(heads[current])
            if current < 0 or current > n:
                return False
        if len(visited) > n:
            return False
    return True


def brute_force_enumerate(scores_np, n):
    """Enumerate all valid arborescences for small n."""
    trees = []
    choices = [
        [i for i in range(n + 1) if i != j]
        for j in range(1, n + 1)
    ]
    for heads_tuple in itertools.product(*choices):
        heads = [-1] + list(heads_tuple)
        if is_valid_arborescence(heads, n):
            log_w = sum(scores_np[heads[j]][j] for j in range(1, n + 1))
            w = np.exp(log_w)
            trees.append((heads, w, log_w))
    return trees


def build_kirchhoff_reference(scores_np, n):
    """Build Kirchhoff matrix independently for reference checks."""
    weights = np.exp(scores_np)
    K = np.zeros((n, n))
    for j in range(1, n + 1):
        for i in range(n + 1):
            if i != j:
                K[j - 1][j - 1] += weights[i][j]
        for i in range(1, n + 1):
            if i != j:
                K[j - 1][i - 1] = -weights[i][j]
    return K


# ============================================================
# Partition function tests
# ============================================================
class TestLogPartition:
    def test_small_brute_force(self):
        from arborescence import log_partition
        inst = load_instance('small')
        scores = np.array(inst['scores'])
        n = inst['n']

        trees = brute_force_enumerate(scores, n)
        Z = sum(w for _, w, _ in trees)
        expected = np.log(Z)

        result = log_partition(scores)
        assert abs(result - expected) < 1e-8, \
            f"Expected {expected}, got {result}"

    def test_medium_kirchhoff(self):
        from arborescence import log_partition
        inst = load_instance('medium')
        scores = np.array(inst['scores'])
        n = inst['n']

        K = build_kirchhoff_reference(scores, n)
        sign, logdet = np.linalg.slogdet(K)
        assert sign > 0
        expected = logdet

        result = log_partition(scores)
        assert abs(result - expected) < 1e-6, \
            f"Expected {expected}, got {result}"

    def test_large_kirchhoff(self):
        from arborescence import log_partition
        inst = load_instance('large')
        scores = np.array(inst['scores'])
        n = inst['n']

        K = build_kirchhoff_reference(scores, n)
        sign, logdet = np.linalg.slogdet(K)
        assert sign > 0
        expected = logdet

        result = log_partition(scores)
        assert abs(result - expected) < 1e-4, \
            f"Expected {expected}, got {result}"

    def test_uniform_scores(self):
        """All scores zero => all weights 1 => known number of trees."""
        from arborescence import log_partition
        n = 4
        scores = np.zeros((n + 1, n + 1))
        trees = brute_force_enumerate(scores, n)
        expected = np.log(len(trees))
        result = log_partition(scores)
        assert abs(result - expected) < 1e-8


# ============================================================
# Arc marginals tests
# ============================================================
class TestArcMarginals:
    def test_small_brute_force(self):
        from arborescence import arc_marginals
        inst = load_instance('small')
        scores = np.array(inst['scores'])
        n = inst['n']

        trees = brute_force_enumerate(scores, n)
        Z = sum(w for _, w, _ in trees)
        expected = np.zeros((n + 1, n + 1))
        for heads, w, _ in trees:
            for j in range(1, n + 1):
                expected[heads[j]][j] += w / Z

        result = arc_marginals(scores)
        for i in range(n + 1):
            for j in range(1, n + 1):
                if i != j:
                    assert abs(result[i][j] - expected[i][j]) < 1e-8, \
                        f"marginal[{i}][{j}]: expected {expected[i][j]:.10f}, got {result[i][j]:.10f}"

    def test_sum_to_one(self):
        from arborescence import arc_marginals
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            n = inst['n']
            result = arc_marginals(scores)
            for j in range(1, n + 1):
                s = sum(result[i][j] for i in range(n + 1) if i != j)
                assert abs(s - 1.0) < 1e-6, \
                    f"{name}: sum for dependent j={j} is {s}, expected 1.0"

    def test_nonnegative(self):
        from arborescence import arc_marginals
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            n = inst['n']
            result = arc_marginals(scores)
            for i in range(n + 1):
                for j in range(1, n + 1):
                    if i != j:
                        assert result[i][j] >= -1e-8, \
                            f"{name}: negative marginal[{i}][{j}] = {result[i][j]}"

    def test_total_sum_equals_n(self):
        from arborescence import arc_marginals
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            n = inst['n']
            result = arc_marginals(scores)
            total = sum(result[i][j] for i in range(n + 1)
                        for j in range(1, n + 1) if i != j)
            assert abs(total - n) < 1e-5, \
                f"{name}: total marginal sum {total}, expected {n}"


# ============================================================
# Entropy tests
# ============================================================
class TestEntropy:
    def test_small_brute_force(self):
        from arborescence import entropy
        inst = load_instance('small')
        scores = np.array(inst['scores'])
        n = inst['n']

        trees = brute_force_enumerate(scores, n)
        Z = sum(w for _, w, _ in trees)
        expected = -sum((w / Z) * np.log(w / Z) for _, w, _ in trees)

        result = entropy(scores)
        assert abs(result - expected) < 1e-8, \
            f"Expected {expected}, got {result}"

    def test_nonnegative(self):
        from arborescence import entropy
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            result = entropy(scores)
            assert result >= -1e-8, f"{name}: entropy {result} < 0"

    def test_uniform_max_entropy(self):
        from arborescence import entropy
        n = 4
        scores = np.zeros((n + 1, n + 1))
        trees = brute_force_enumerate(scores, n)
        expected = np.log(len(trees))
        result = entropy(scores)
        assert abs(result - expected) < 1e-8, \
            f"Uniform: expected {expected}, got {result}"

    def test_entropy_upper_bound(self):
        from arborescence import entropy
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            n = inst['n']
            result = entropy(scores)
            upper = n * np.log(n + 1)
            assert result <= upper + 0.1, \
                f"{name}: entropy {result} exceeds upper bound {upper}"


# ============================================================
# MAP tree tests
# ============================================================
class TestMapTree:
    def test_small_brute_force(self):
        from arborescence import map_tree
        inst = load_instance('small')
        scores = np.array(inst['scores'])
        n = inst['n']

        heads = map_tree(scores)
        assert is_valid_arborescence(heads, n), f"Invalid tree: {heads}"

        trees = brute_force_enumerate(scores, n)
        best_score = max(lw for _, _, lw in trees)
        got_score = sum(scores[int(heads[j])][j] for j in range(1, n + 1))
        assert abs(got_score - best_score) < 1e-8, \
            f"MAP score {got_score} != best {best_score}"

    def test_valid_arborescence_all(self):
        from arborescence import map_tree
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            n = inst['n']
            heads = map_tree(scores)
            assert is_valid_arborescence(heads, n), \
                f"{name}: invalid arborescence: {heads}"

    def test_local_optimality(self):
        """No single-arc swap should improve the MAP tree score."""
        from arborescence import map_tree
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            n = inst['n']
            heads = map_tree(scores)
            map_score = sum(scores[int(heads[j])][j] for j in range(1, n + 1))

            for j in range(1, n + 1):
                for alt in range(n + 1):
                    if alt == j or alt == int(heads[j]):
                        continue
                    alt_heads = [int(h) for h in heads]
                    alt_heads[j] = alt
                    if is_valid_arborescence(alt_heads, n):
                        alt_score = sum(
                            scores[alt_heads[k]][k]
                            for k in range(1, n + 1)
                        )
                        assert alt_score <= map_score + 1e-10, \
                            f"{name}: swapping head of {j} from {int(heads[j])} to {alt} " \
                            f"gives better score {alt_score} > {map_score}"


# ============================================================
# Expected attachment score tests
# ============================================================
class TestExpectedAttachment:
    def test_small_via_marginals(self):
        from arborescence import expected_attachment_score, arc_marginals
        inst = load_instance('small')
        scores = np.array(inst['scores'])
        n = inst['n']
        gold = inst['gold_heads']

        result = expected_attachment_score(scores, gold)
        marginals = arc_marginals(scores)
        expected = sum(marginals[gold[j]][j] for j in range(1, n + 1)) / n
        assert abs(result - expected) < 1e-8

    def test_bounds(self):
        from arborescence import expected_attachment_score
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            scores = np.array(inst['scores'])
            gold = inst['gold_heads']
            result = expected_attachment_score(scores, gold)
            assert -1e-8 <= result <= 1.0 + 1e-8, \
                f"{name}: EAS {result} out of [0,1]"


# ============================================================
# KL divergence tests
# ============================================================
class TestKLDivergence:
    def test_self_is_zero(self):
        from arborescence import kl_divergence
        inst = load_instance('small')
        scores = np.array(inst['scores'])
        result = kl_divergence(scores, scores)
        assert abs(result) < 1e-8, f"KL(P||P) = {result} != 0"

    def test_nonnegative(self):
        from arborescence import kl_divergence
        p = np.array(load_instance('small')['scores'])
        q = np.array(load_instance('small_alt')['scores'])
        assert kl_divergence(p, q) >= -1e-8, \
            f"KL(P||Q) = {kl_divergence(p, q)} < 0"
        assert kl_divergence(q, p) >= -1e-8, \
            f"KL(Q||P) = {kl_divergence(q, p)} < 0"

    def test_small_brute_force(self):
        from arborescence import kl_divergence
        inst_p = load_instance('small')
        inst_q = load_instance('small_alt')
        sp = np.array(inst_p['scores'])
        sq = np.array(inst_q['scores'])
        n = inst_p['n']

        trees = brute_force_enumerate(sp, n)

        Z_p = sum(w for _, w, _ in trees)
        Z_q = 0.0
        tree_q_weights = []
        for heads, _, _ in trees:
            lw_q = sum(sq[heads[j]][j] for j in range(1, n + 1))
            w_q = np.exp(lw_q)
            Z_q += w_q
            tree_q_weights.append(w_q)

        expected = 0.0
        for idx, (heads, w_p, _) in enumerate(trees):
            p_prob = w_p / Z_p
            q_prob = tree_q_weights[idx] / Z_q
            if p_prob > 0 and q_prob > 0:
                expected += p_prob * np.log(p_prob / q_prob)

        result = kl_divergence(sp, sq)
        assert abs(result - expected) < 1e-7, \
            f"KL brute force: expected {expected}, got {result}"

    def test_asymmetry(self):
        """KL is generally asymmetric."""
        from arborescence import kl_divergence
        p = np.array(load_instance('small')['scores'])
        q = np.array(load_instance('small_alt')['scores'])
        kl_pq = kl_divergence(p, q)
        kl_qp = kl_divergence(q, p)
        assert kl_pq >= -1e-8
        assert kl_qp >= -1e-8


# ============================================================
# SQLite output table tests
# ============================================================
class TestSQLiteOutput:
    def _get_conn(self):
        return sqlite3.connect(DB_PATH)

    def test_output_tables_exist(self):
        conn = self._get_conn()
        c = conn.cursor()
        for table in ['computed_partition', 'computed_entropy',
                       'computed_map_heads', 'computed_eas', 'computed_kl']:
            c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            assert c.fetchone() is not None, f"Table {table} does not exist in database"
        conn.close()

    def test_partition_all_instances_present(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT instance_id, log_z FROM computed_partition")
        rows = {r[0]: r[1] for r in c.fetchall()}
        conn.close()
        for name in ['small', 'small_alt', 'medium', 'large']:
            assert name in rows, f"Missing partition result for {name}"
            assert isinstance(rows[name], float), f"log_z for {name} not a float"

    def test_partition_small_matches_brute_force(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT log_z FROM computed_partition WHERE instance_id = 'small'")
        row = c.fetchone()
        conn.close()
        assert row is not None, "No partition result for 'small'"

        inst = load_instance('small')
        trees = brute_force_enumerate(inst['scores'], inst['n'])
        Z = sum(w for _, w, _ in trees)
        expected = np.log(Z)
        assert abs(row[0] - expected) < 1e-6, \
            f"DB log_z {row[0]} != brute force {expected}"

    def test_entropy_all_present(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT instance_id, entropy_nats FROM computed_entropy")
        rows = {r[0]: r[1] for r in c.fetchall()}
        conn.close()
        for name in ['small', 'small_alt', 'medium', 'large']:
            assert name in rows, f"Missing entropy for {name}"
            assert rows[name] >= -1e-6, f"Negative entropy for {name}: {rows[name]}"

    def test_map_heads_valid_arborescences(self):
        conn = self._get_conn()
        c = conn.cursor()
        for name in ['small', 'small_alt', 'medium', 'large']:
            inst = load_instance(name)
            n = inst['n']
            c.execute(
                "SELECT node, head FROM computed_map_heads WHERE instance_id = ? ORDER BY node",
                (name,)
            )
            rows = c.fetchall()
            assert len(rows) >= n, \
                f"{name}: expected >= {n} head entries, got {len(rows)}"
            heads = [-1] * (n + 1)
            for node, head in rows:
                heads[node] = head
            assert is_valid_arborescence(heads, n), \
                f"{name}: invalid arborescence stored in DB: {heads}"
        conn.close()

    def test_eas_in_range(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT instance_id, score FROM computed_eas")
        rows = c.fetchall()
        conn.close()
        assert len(rows) >= 4, f"Expected >= 4 EAS entries, got {len(rows)}"
        for name, score in rows:
            assert 0 <= score <= 1 + 1e-6, \
                f"{name}: EAS {score} out of [0, 1]"

    def test_kl_self_divergence_zero(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT instance_id_p, instance_id_q, kl_value "
            "FROM computed_kl WHERE instance_id_p = instance_id_q"
        )
        rows = c.fetchall()
        conn.close()
        assert len(rows) > 0, "No self-KL entries found"
        for p, q, kl in rows:
            assert abs(kl) < 1e-6, f"KL({p}||{q}) = {kl}, expected ~0"

    def test_kl_nonnegative(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT instance_id_p, instance_id_q, kl_value FROM computed_kl")
        rows = c.fetchall()
        conn.close()
        assert len(rows) >= 4, f"Expected >= 4 KL entries, got {len(rows)}"
        for p, q, kl in rows:
            assert kl >= -1e-6, f"KL({p}||{q}) = {kl} < 0"

    def test_kl_cross_small_brute_force(self):
        """Verify KL(small||small_alt) stored in DB matches brute force."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT kl_value FROM computed_kl "
            "WHERE instance_id_p = 'small' AND instance_id_q = 'small_alt'"
        )
        row = c.fetchone()
        conn.close()
        assert row is not None, "KL(small||small_alt) not found in DB"

        inst_p = load_instance('small')
        inst_q = load_instance('small_alt')
        sp = np.array(inst_p['scores'])
        sq = np.array(inst_q['scores'])
        n = inst_p['n']
        trees = brute_force_enumerate(sp, n)
        Z_p = sum(w for _, w, _ in trees)
        tree_q_weights = []
        for heads, _, _ in trees:
            lw_q = sum(sq[heads[j]][j] for j in range(1, n + 1))
            tree_q_weights.append(np.exp(lw_q))
        Z_q = sum(tree_q_weights)
        expected = 0.0
        for idx, (heads, w_p, _) in enumerate(trees):
            p_prob = w_p / Z_p
            q_prob = tree_q_weights[idx] / Z_q
            if p_prob > 0 and q_prob > 0:
                expected += p_prob * np.log(p_prob / q_prob)

        assert abs(row[0] - expected) < 1e-6, \
            f"DB KL {row[0]} != brute force {expected}"


# ============================================================
# Visualization tests (graphviz SVG output)
# ============================================================
class TestVisualization:
    def test_svg_files_exist(self):
        for name in ['small', 'small_alt', 'medium', 'large']:
            path = f'/app/output/{name}_map.svg'
            assert os.path.isfile(path), f"Missing SVG file: {path}"

    def test_svg_nonempty(self):
        for name in ['small', 'small_alt', 'medium', 'large']:
            path = f'/app/output/{name}_map.svg'
            size = os.path.getsize(path)
            assert size > 100, f"{path}: file too small ({size} bytes)"

    def test_svg_contains_svg_tag(self):
        for name in ['small', 'small_alt', 'medium', 'large']:
            path = f'/app/output/{name}_map.svg'
            with open(path) as f:
                content = f.read()
            assert '<svg' in content, f"{path}: does not contain <svg> tag"

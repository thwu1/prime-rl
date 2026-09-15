
import json
import os
import random
import subprocess
import sqlite3

import duckdb
import pytest

DB_PATH = '/app/tree.db'
ANALYTICS_DB = '/app/analytics.duckdb'


def get_ancestors_ground_truth(node_id):
    """Walk parent pointers to compute ground truth ancestor path."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    path = []
    current = node_id
    visited = set()
    while current is not None:
        if current in visited:
            break
        visited.add(current)
        path.append(current)
        row = c.execute(
            'SELECT parent_id FROM tree WHERE id = ?', (current,)
        ).fetchone()
        if row is None:
            break
        current = row[0]
    conn.close()
    return path


def get_lca_ground_truth(a, b):
    """Compute LCA via ancestor-path intersection."""
    ancestors_a = get_ancestors_ground_truth(a)
    ancestors_b_set = set(get_ancestors_ground_truth(b))
    for node in ancestors_a:
        if node in ancestors_b_set:
            return node
    return None


def run_api(*args, timeout=60):
    """Run the pipeline CLI and return stdout."""
    result = subprocess.run(
        ['python3', '/app/pipeline/api.py'] + [str(a) for a in args],
        capture_output=True, text=True, timeout=timeout
    )
    assert result.returncode == 0, (
        f"api.py {' '.join(str(a) for a in args)} failed "
        f"(rc={result.returncode}): {result.stderr[:500]}"
    )
    return result.stdout.strip()


@pytest.fixture(scope='session', autouse=True)
def build_index():
    """Run build once before all tests."""
    run_api('build', timeout=120)


# ---------------------------------------------------------------------------
# Ancestor query correctness
# ---------------------------------------------------------------------------

class TestAncestors:
    def test_ancestors_root(self):
        output = run_api('ancestors', 0)
        assert json.loads(output) == [0]

    def test_ancestors_depth_1(self):
        output = run_api('ancestors', 1)
        assert json.loads(output) == get_ancestors_ground_truth(1)

    def test_ancestors_backbone_mid(self):
        output = run_api('ancestors', 30)
        ancestors = json.loads(output)
        expected = get_ancestors_ground_truth(30)
        assert ancestors == expected
        assert len(ancestors) == 31

    def test_ancestors_backbone_end(self):
        output = run_api('ancestors', 60)
        assert json.loads(output) == get_ancestors_ground_truth(60)

    @pytest.mark.parametrize(
        "node_id", [100, 500, 1000, 2500, 5000, 7500, 9999]
    )
    def test_ancestors_various(self, node_id):
        output = run_api('ancestors', node_id)
        ancestors = json.loads(output)
        expected = get_ancestors_ground_truth(node_id)
        assert ancestors == expected, (
            f"Node {node_id}: expected len {len(expected)}, "
            f"got len {len(ancestors)}"
        )

    def test_ancestors_start_and_end(self):
        """First element is the queried node, last element is root."""
        for nid in [10, 200, 4000, 8888]:
            output = run_api('ancestors', nid)
            ancestors = json.loads(output)
            assert ancestors[0] == nid, (
                f"Node {nid}: path should start with {nid}"
            )
            assert ancestors[-1] == 0, (
                f"Node {nid}: path should end at root 0"
            )

    def test_ancestors_batch(self):
        """Correctness over a pseudorandom sample of 30 nodes."""
        rng = random.Random(12345)
        for nid in rng.sample(range(10000), 30):
            output = run_api('ancestors', nid)
            ancestors = json.loads(output)
            expected = get_ancestors_ground_truth(nid)
            assert ancestors == expected, (
                f"Ancestors of {nid}: expected len {len(expected)}, "
                f"got len {len(ancestors)}"
            )


# ---------------------------------------------------------------------------
# LCA query correctness
# ---------------------------------------------------------------------------

class TestLCA:
    def test_lca_same_node(self):
        output = run_api('lca', 42, 42)
        assert int(output) == 42

    def test_lca_root_and_other(self):
        output = run_api('lca', 0, 500)
        assert int(output) == 0

    def test_lca_ancestor_descendant(self):
        """LCA of a node and its descendant on the backbone."""
        output = run_api('lca', 20, 50)
        assert int(output) == 20

    @pytest.mark.parametrize(
        "a,b", [(100, 200), (500, 1000), (3000, 7000), (1, 9999), (61, 62)]
    )
    def test_lca_various(self, a, b):
        output = run_api('lca', a, b)
        expected = get_lca_ground_truth(a, b)
        assert int(output) == expected, (
            f"LCA({a}, {b}): expected {expected}, got {output}"
        )

    def test_lca_symmetry(self):
        """LCA(a,b) must equal LCA(b,a)."""
        for a, b in [(100, 300), (50, 5000)]:
            out1 = int(run_api('lca', a, b))
            out2 = int(run_api('lca', b, a))
            assert out1 == out2, (
                f"LCA({a},{b})={out1} != LCA({b},{a})={out2}"
            )

    def test_lca_batch(self):
        """Correctness over pseudorandom node pairs."""
        rng = random.Random(54321)
        for _ in range(15):
            a, b = rng.sample(range(10000), 2)
            output = run_api('lca', a, b)
            expected = get_lca_ground_truth(a, b)
            assert int(output) == expected, (
                f"LCA({a}, {b}): expected {expected}, got {output}"
            )


# ---------------------------------------------------------------------------
# Production constraint and integrity checks
# ---------------------------------------------------------------------------

class TestConstraints:
    def _all_py_sources(self):
        """Read all Python source files under /app/."""
        sources = {}
        for dirpath, _, filenames in os.walk('/app'):
            for fn in filenames:
                if fn.endswith('.py'):
                    fpath = os.path.join(dirpath, fn)
                    with open(fpath) as f:
                        sources[fpath] = f.read()
        return sources

    def test_no_recursive_cte(self):
        """No Python file under /app/ may use WITH RECURSIVE."""
        for path, src in self._all_py_sources().items():
            assert 'WITH RECURSIVE' not in src.upper(), (
                f"{path} contains WITH RECURSIVE — "
                f"violates production constraint"
            )

    def test_uses_join_sql(self):
        """At least one Python file under /app/ must use SQL JOINs."""
        sources = self._all_py_sources()
        assert any('JOIN' in s.upper() for s in sources.values()), (
            "No Python file under /app/ uses SQL JOINs — "
            "queries must use join-based SQL"
        )

    def test_tree_table_unchanged(self):
        """The original tree table must not be modified."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        count = c.execute('SELECT COUNT(*) FROM tree').fetchone()[0]
        assert count == 10000, (
            f"tree table should have 10000 rows, has {count}"
        )
        root = c.execute(
            'SELECT id FROM tree WHERE parent_id IS NULL'
        ).fetchone()
        assert root is not None and root[0] == 0, (
            "Root node (id=0) missing or changed"
        )
        conn.close()

    def test_analytics_db_tables(self):
        """Build must create >=3 non-empty auxiliary tables in DuckDB."""
        assert os.path.exists(ANALYTICS_DB), (
            "DuckDB analytics database not found at /app/analytics.duckdb"
        )
        conn = duckdb.connect(ANALYTICS_DB, read_only=True)
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
        nonempty = 0
        for (name,) in tables:
            cnt = conn.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]
            if cnt > 0:
                nonempty += 1
        conn.close()
        assert nonempty >= 3, (
            f"Expected >= 3 non-empty auxiliary tables in analytics.duckdb, "
            f"found {nonempty}"
        )

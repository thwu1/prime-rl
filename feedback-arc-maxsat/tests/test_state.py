import json
import os
import pytest
from collections import defaultdict


INSTANCE_DIR = '/app/instances'
WCNF_DIR = '/app/wcnf'
RESULTS_FILE = '/app/results.json'


def read_graph(filepath):
    with open(filepath) as f:
        n, m = map(int, f.readline().split())
        edges = []
        for _ in range(m):
            u, v, w = map(int, f.readline().split())
            edges.append((u, v, w))
    return n, edges


def has_cycle(n, adj):
    """DFS-based cycle detection on a directed graph."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = defaultdict(int)

    def dfs(u):
        color[u] = GRAY
        for v in adj.get(u, []):
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    for u in range(1, n + 1):
        if color[u] == WHITE and dfs(u):
            return True
    return False


def compute_optimal_fas(n, edges):
    """Independently compute optimal FAS weight using MaxSAT encoding."""
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF

    wcnf = WCNF()
    var_map = {}
    idx = 0
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            idx += 1
            var_map[(i, j)] = idx

    # Transitivity hard clauses
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            for k in range(j + 1, n + 1):
                xij = var_map[(i, j)]
                xjk = var_map[(j, k)]
                xik = var_map[(i, k)]
                wcnf.append([-xij, -xjk, xik])
                wcnf.append([xij, xjk, -xik])

    # Soft clauses for edges
    for u, v, w in edges:
        if u < v:
            lit = var_map[(u, v)]
        else:
            lit = -var_map[(v, u)]
        wcnf.append([lit], weight=w)

    with RC2(wcnf) as solver:
        solver.compute()
        return solver.cost


def get_instances():
    result = {}
    for fn in sorted(os.listdir(INSTANCE_DIR)):
        if fn.endswith('.txt'):
            name = fn[:-4]
            result[name] = read_graph(os.path.join(INSTANCE_DIR, fn))
    return result


@pytest.fixture(scope='module')
def results():
    with open(RESULTS_FILE) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def instances():
    return get_instances()


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_FILE), 'results.json not found'

    def test_all_instances_present(self, results, instances):
        for name in instances:
            assert name in results, f'Missing instance {name}'

    def test_wcnf_directory_exists(self):
        assert os.path.isdir(WCNF_DIR), 'wcnf/ directory not found'

    def test_wcnf_files_exist(self, instances):
        for name in instances:
            path = os.path.join(WCNF_DIR, f'{name}.wcnf')
            assert os.path.isfile(path), f'Missing WCNF file {path}'


class TestWcnfValidity:
    def test_wcnf_header_format(self, instances):
        """Verify each WCNF file has a valid header."""
        for name in instances:
            path = os.path.join(WCNF_DIR, f'{name}.wcnf')
            with open(path) as f:
                found_header = False
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('c'):
                        continue
                    if line.startswith('p wcnf'):
                        parts = line.split()
                        assert len(parts) == 5, f'{name}: bad WCNF header'
                        num_vars = int(parts[2])
                        num_clauses = int(parts[3])
                        top_weight = int(parts[4])
                        assert num_vars > 0
                        assert num_clauses > 0
                        assert top_weight > 0
                        found_header = True
                        break
                assert found_header, f'{name}: no WCNF header found'

    def test_wcnf_clauses_terminated(self, instances):
        """Verify all clauses end with 0."""
        for name in instances:
            path = os.path.join(WCNF_DIR, f'{name}.wcnf')
            with open(path) as f:
                past_header = False
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('c'):
                        continue
                    if line.startswith('p '):
                        past_header = True
                        continue
                    if past_header:
                        parts = line.split()
                        assert parts[-1] == '0', \
                            f'{name}: clause not terminated by 0: {line[:60]}'


class TestSolutionValidity:
    def test_fas_edges_in_graph(self, results, instances):
        for name, (n, edges) in instances.items():
            edge_set = {(u, v) for u, v, _ in edges}
            for fe in results[name]['fas_edges']:
                assert (fe[0], fe[1]) in edge_set, \
                    f'{name}: FAS edge ({fe[0]},{fe[1]}) not in graph'

    def test_fas_weight_computation(self, results, instances):
        for name, (n, edges) in instances.items():
            ew = {(u, v): w for u, v, w in edges}
            computed = sum(ew[(e[0], e[1])] for e in results[name]['fas_edges'])
            assert computed == results[name]['fas_weight'], \
                f'{name}: weight {results[name]["fas_weight"]} != sum {computed}'

    def test_dag_after_removal(self, results, instances):
        for name, (n, edges) in instances.items():
            fas = {(e[0], e[1]) for e in results[name]['fas_edges']}
            adj = defaultdict(list)
            for u, v, _ in edges:
                if (u, v) not in fas:
                    adj[u].append(v)
            assert not has_cycle(n, adj), \
                f'{name}: still cyclic after FAS removal'

    def test_ordering_permutation(self, results, instances):
        for name, (n, edges) in instances.items():
            ordering = results[name]['ordering']
            assert sorted(ordering) == list(range(1, n + 1)), \
                f'{name}: ordering is not a valid permutation of 1..{n}'

    def test_ordering_consistent(self, results, instances):
        for name, (n, edges) in instances.items():
            ordering = results[name]['ordering']
            fas = {(e[0], e[1]) for e in results[name]['fas_edges']}
            pos = {v: i for i, v in enumerate(ordering)}
            for u, v, _ in edges:
                if (u, v) not in fas:
                    assert pos[u] < pos[v], \
                        f'{name}: non-FAS edge ({u},{v}) backward in ordering'


class TestOptimality:
    def test_optimal_cost(self, results, instances):
        """Independently verify each FAS weight is optimal."""
        for name, (n, edges) in instances.items():
            optimal = compute_optimal_fas(n, edges)
            assert results[name]['fas_weight'] == optimal, \
                f'{name}: weight {results[name]["fas_weight"]} != optimal {optimal}'

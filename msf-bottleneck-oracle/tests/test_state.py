
import html
import json
import os
import re
import sqlite3
import pytest
import networkx as nx
from collections import defaultdict, deque

DB = '/app/network/topology.db'
CONFIG = '/app/network/config.json'
RESULTS = '/app/results.json'
SVG_PATH = '/app/output/msf.svg'


@pytest.fixture(scope="module")
def config():
    with open(CONFIG) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def graph_from_db():
    """Reconstruct the graph from the SQLite database per the config rules."""
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Active nodes only
    c.execute("SELECT node_id, hostname FROM nodes WHERE status='active'")
    active_nodes = dict(c.fetchall())
    active_set = set(active_nodes.keys())
    hostname_to_id = {v: k for k, v in active_nodes.items()}

    # Qualifying edges: non-self-loop, both endpoints active, has measurements,
    # weight from latest measurement
    c.execute("""
        SELECT e.edge_id, e.src_node, e.dst_node,
               m.latency_us + 100 * m.loss_permille + m.jitter_us
        FROM edges e
        JOIN measurements m ON m.edge_id = e.edge_id
        WHERE e.src_node != e.dst_node
          AND m.collected_at = (
              SELECT MAX(m2.collected_at)
              FROM measurements m2
              WHERE m2.edge_id = e.edge_id
          )
    """)

    G = nx.Graph()
    G.add_nodes_from(active_set)
    all_edges = []

    for _, src, dst, w in c.fetchall():
        if src in active_set and dst in active_set:
            G.add_edge(src, dst, weight=w)
            all_edges.append((src, dst, w))

    # Queries
    c.execute(
        "SELECT query_id, src_hostname, dst_hostname "
        "FROM analysis_queries ORDER BY query_id"
    )
    queries = c.fetchall()

    conn.close()
    return G, active_nodes, hostname_to_id, all_edges, queries


@pytest.fixture(scope="module")
def msf_data(graph_from_db):
    """Compute MSF and derived structures using networkx."""
    G, active_nodes, hostname_to_id, all_edges, queries = graph_from_db

    msf = nx.minimum_spanning_tree(G, algorithm='kruskal')
    msf_weight = sum(d['weight'] for _, _, d in msf.edges(data=True))

    components = list(nx.connected_components(G))
    comp_map = {}
    for comp in components:
        rep = min(comp)
        for n in comp:
            comp_map[n] = rep

    msf_adj = defaultdict(list)
    msf_edge_set = set()
    for u, v, d in msf.edges(data=True):
        w = d['weight']
        msf_adj[u].append((v, w))
        msf_adj[v].append((u, w))
        msf_edge_set.add((min(u, v), max(u, v)))

    return {
        'msf': msf,
        'msf_weight': msf_weight,
        'num_components': len(components),
        'component_sizes': sorted(len(c) for c in components),
        'comp_map': comp_map,
        'msf_adj': dict(msf_adj),
        'msf_edge_set': msf_edge_set,
        'active_nodes': active_nodes,
        'hostname_to_id': hostname_to_id,
        'all_edges': all_edges,
        'queries': queries,
        'G': G,
    }


@pytest.fixture(scope="module")
def results():
    with open(RESULTS) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def svg_content():
    with open(SVG_PATH) as f:
        return f.read()


def _bottleneck_bfs(u, v, comp_map, msf_adj):
    """BFS on MSF tree to find max edge weight on path u->v."""
    if comp_map.get(u) != comp_map.get(v):
        return -1
    if u == v:
        return 0
    visited = {u}
    queue = deque([(u, 0)])
    while queue:
        node, mx = queue.popleft()
        for nbr, w in msf_adj.get(node, []):
            if nbr not in visited:
                visited.add(nbr)
                nm = max(mx, w)
                if nbr == v:
                    return nm
                queue.append((nbr, nm))
    return -1


# -- JSON results tests --

def test_results_file_exists(results):
    assert isinstance(results, dict), "results.json must be a JSON object"


def test_required_keys(results):
    required = [
        'active_node_count', 'edge_count', 'num_components',
        'component_sizes', 'msf_total_weight', 'bottleneck_answers',
        'critical_edges', 'second_best_msf_weight',
    ]
    for key in required:
        assert key in results, f"Missing key: {key}"


def test_active_node_count(results, graph_from_db):
    _, active_nodes, _, _, _ = graph_from_db
    assert results['active_node_count'] == len(active_nodes)


def test_edge_count(results, graph_from_db):
    _, _, _, all_edges, _ = graph_from_db
    assert results['edge_count'] == len(all_edges)


def test_num_components(results, msf_data):
    assert results['num_components'] == msf_data['num_components']


def test_component_sizes(results, msf_data):
    assert results['component_sizes'] == msf_data['component_sizes']


def test_msf_total_weight(results, msf_data):
    assert results['msf_total_weight'] == msf_data['msf_weight']


def test_bottleneck_answers(results, msf_data):
    comp_map = msf_data['comp_map']
    msf_adj = msf_data['msf_adj']
    hostname_to_id = msf_data['hostname_to_id']

    expected = []
    for _, src_h, dst_h in msf_data['queries']:
        src_id = hostname_to_id.get(src_h)
        dst_id = hostname_to_id.get(dst_h)
        if src_id is None or dst_id is None:
            expected.append(-1)
        else:
            expected.append(_bottleneck_bfs(src_id, dst_id, comp_map, msf_adj))

    got = results['bottleneck_answers']
    assert len(got) == len(expected), \
        f"Expected {len(expected)} answers, got {len(got)}"
    mismatches = [
        (i, e, g) for i, (e, g) in enumerate(zip(expected, got)) if e != g
    ]
    assert len(mismatches) == 0, \
        f"{len(mismatches)} wrong answers; first 5: {mismatches[:5]}"


def test_critical_edges(results, msf_data, config):
    msf = msf_data['msf']
    G = msf_data['G']
    msf_edge_set = msf_data['msf_edge_set']
    active_nodes = msf_data['active_nodes']

    threshold = None
    for analysis in config['analyses']:
        if analysis['id'] == 'critical':
            threshold = analysis['threshold']
            break
    assert threshold is not None

    expected = []
    for u, v, d in msf.edges(data=True):
        w_e = d['weight']

        # Remove edge from MSF copy to find the two subtrees
        msf_copy = msf.copy()
        msf_copy.remove_edge(u, v)
        comp_u = set(nx.node_connected_component(msf_copy, u))

        # Find best replacement: non-MSF edge crossing the cut
        best_replacement = float('inf')
        for a, b, gd in G.edges(data=True):
            key = (min(a, b), max(a, b))
            if key in msf_edge_set:
                continue
            if (a in comp_u) != (b in comp_u):
                best_replacement = min(best_replacement, gd['weight'])

        if best_replacement == float('inf') or best_replacement - w_e > threshold:
            hn = sorted([active_nodes[u], active_nodes[v]])
            expected.append([hn[0], hn[1], w_e])

    expected.sort(key=lambda x: x[2])
    assert results['critical_edges'] == expected, \
        f"Expected {len(expected)} critical edges, got {len(results['critical_edges'])}"


def test_second_best_msf_weight(results, msf_data):
    msf_weight = msf_data['msf_weight']
    msf_edge_set = msf_data['msf_edge_set']
    comp_map = msf_data['comp_map']
    msf_adj = msf_data['msf_adj']

    min_swap = float('inf')
    for s, d, w in msf_data['all_edges']:
        key = (min(s, d), max(s, d))
        if key in msf_edge_set:
            continue
        bn = _bottleneck_bfs(s, d, comp_map, msf_adj)
        if bn < 0:
            continue
        min_swap = min(min_swap, w - bn)

    expected = -1 if min_swap == float('inf') else msf_weight + min_swap
    assert results['second_best_msf_weight'] == expected


# -- SVG visualization tests --

def test_svg_file_exists():
    assert os.path.exists(SVG_PATH), f"SVG file not found at {SVG_PATH}"


def test_svg_generated_by_graphviz(svg_content):
    assert 'Generated by graphviz' in svg_content or 'Graphviz' in svg_content, \
        "SVG must be generated by Graphviz (dot command)"


def test_svg_node_count(svg_content, msf_data):
    node_elements = re.findall(r'class="node"', svg_content)
    expected_nodes = len(msf_data['active_nodes'])
    assert len(node_elements) == expected_nodes, \
        f"Expected {expected_nodes} nodes in SVG, found {len(node_elements)}"


def test_svg_edge_count(svg_content, msf_data):
    edge_elements = re.findall(r'class="edge"', svg_content)
    expected_edges = len(list(msf_data['msf'].edges()))
    assert len(edge_elements) == expected_edges, \
        f"Expected {expected_edges} MSF edges in SVG, found {len(edge_elements)}"


def test_svg_contains_hostnames(svg_content, msf_data):
    # Graphviz SVG output may XML-encode characters (e.g. hyphens as &#45;),
    # so unescape before checking for hostnames.
    decoded = html.unescape(svg_content)
    hostnames = list(msf_data['active_nodes'].values())
    missing = [h for h in hostnames if h not in decoded]
    assert len(missing) == 0, \
        f"{len(missing)} hostnames missing from SVG; first 5: {missing[:5]}"

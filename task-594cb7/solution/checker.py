#!/usr/bin/env python3
"""
Jepsen EDN history consistency checker with full dependency graph analysis.
Parses Jepsen operation histories in EDN format using a built-in parser,
builds transactional dependency graphs, detects consistency anomalies,
performs SCC decomposition, computes minimum feedback vertex sets, and
produces graphviz visualizations.
"""

import json
import subprocess
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path


# ---------------------------------------------------------------------------
# Minimal EDN parser — handles the subset used in Jepsen operation histories:
#   vectors, maps, keywords, integers, nil, true, false
# ---------------------------------------------------------------------------

class EdnParser:
    """Recursive-descent parser for Jepsen EDN history files."""

    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.length = len(text)

    def _skip(self):
        """Skip whitespace, commas, and ;-comments."""
        while self.pos < self.length:
            c = self.text[self.pos]
            if c in ' \t\n\r,':
                self.pos += 1
            elif c == ';':
                while self.pos < self.length and self.text[self.pos] != '\n':
                    self.pos += 1
            else:
                break

    def parse(self):
        self._skip()
        if self.pos >= self.length:
            raise ValueError("Unexpected end of input")
        c = self.text[self.pos]
        if c == '[':
            return self._parse_vector()
        if c == '{':
            return self._parse_map()
        if c == ':':
            return self._parse_keyword()
        if c == '-' and self.pos + 1 < self.length and self.text[self.pos + 1].isdigit():
            return self._parse_number()
        if c.isdigit():
            return self._parse_number()
        # literals
        rest = self.text[self.pos:]
        if rest.startswith('nil'):
            self.pos += 3
            return None
        if rest.startswith('true'):
            self.pos += 4
            return True
        if rest.startswith('false'):
            self.pos += 5
            return False
        raise ValueError(f"Unexpected character at pos {self.pos}: {c!r}")

    def _parse_vector(self):
        self.pos += 1  # skip '['
        items = []
        while True:
            self._skip()
            if self.pos < self.length and self.text[self.pos] == ']':
                self.pos += 1
                return items
            items.append(self.parse())

    def _parse_map(self):
        self.pos += 1  # skip '{'
        result = {}
        while True:
            self._skip()
            if self.pos < self.length and self.text[self.pos] == '}':
                self.pos += 1
                return result
            key = self.parse()
            val = self.parse()
            result[key] = val

    def _parse_keyword(self):
        self.pos += 1  # skip ':'
        start = self.pos
        while self.pos < self.length and self.text[self.pos] not in ' \t\n\r,{}[]()':
            self.pos += 1
        return self.text[start:self.pos]

    def _parse_number(self):
        start = self.pos
        if self.text[self.pos] == '-':
            self.pos += 1
        while self.pos < self.length and self.text[self.pos].isdigit():
            self.pos += 1
        return int(self.text[start:self.pos])


def parse_edn(text):
    """Parse an EDN string and return the Python data structure."""
    return EdnParser(text).parse()


def parse_edn_history(path):
    """Parse a Jepsen EDN history file."""
    with open(path) as f:
        return parse_edn(f.read())


# ---------------------------------------------------------------------------
# Transaction extraction
# ---------------------------------------------------------------------------

def extract_committed_transactions(history):
    """
    Match invoke/ok pairs by process. Return only committed (ok) transactions.
    Each has: id, start time, end time, and list of micro-operations.
    """
    pending = {}
    transactions = []
    txn_id = 0

    for op in history:
        proc = op['process']
        typ = op['type']

        if typ == 'invoke':
            pending[proc] = op
        elif typ == 'ok':
            invoke = pending.pop(proc, None)
            if invoke is not None:
                ops = []
                for micro in op['value']:
                    op_type = micro[0]
                    if op_type == 'append':
                        ops.append(('append', micro[1], micro[2]))
                    elif op_type == 'r':
                        observed = list(micro[2]) if micro[2] is not None else []
                        ops.append(('r', micro[1], observed))
                transactions.append({
                    'id': txn_id,
                    'start': invoke['time'],
                    'end': op['time'],
                    'ops': ops,
                })
                txn_id += 1
        elif typ in ('fail', 'info'):
            pending.pop(proc, None)

    return transactions


# ---------------------------------------------------------------------------
# Dependency analysis helpers
# ---------------------------------------------------------------------------

def extract_ops(txns):
    """Extract per-key appends, reads, and value->txn mappings."""
    appends = defaultdict(list)
    reads = defaultdict(list)
    value_to_txn = defaultdict(dict)

    for txn in txns:
        tid = txn['id']
        for op in txn['ops']:
            if op[0] == 'append':
                key, val = op[1], op[2]
                appends[key].append((tid, val))
                value_to_txn[key][val] = tid
            elif op[0] == 'r':
                key, observed = op[1], op[2]
                reads[key].append((tid, observed))

    return appends, reads, value_to_txn


def build_version_order(reads, value_to_txn):
    """
    Determine version order for each key from read observations.
    The longest read of a key establishes the canonical ordering.
    Values not observed in any read are appended at the end in sorted order.
    """
    version_orders = {}
    all_keys = set(reads.keys()) | set(value_to_txn.keys())

    for key in all_keys:
        longest = []
        for _tid, observed in reads.get(key, []):
            if len(observed) > len(longest):
                longest = observed

        order = []
        for val in longest:
            if val in value_to_txn.get(key, {}):
                order.append((val, value_to_txn[key][val]))

        seen_vals = set(longest)
        for val, tid in sorted(value_to_txn.get(key, {}).items()):
            if val not in seen_vals:
                order.append((val, tid))

        version_orders[key] = order

    return version_orders


def build_edges(txns, reads, value_to_txn, version_orders):
    """Build WW, WR, RW, RT dependency edge sets."""
    ww_edges = set()
    wr_edges = set()
    rw_edges = set()
    rt_edges = set()

    # WW: consecutive writes in version order
    for key, order in version_orders.items():
        for i in range(len(order) - 1):
            t1 = order[i][1]
            t2 = order[i + 1][1]
            if t1 != t2:
                ww_edges.add((t1, t2))

    # WR: writer -> reader (reader observed writer's value)
    for key in reads:
        for reader_tid, observed in reads[key]:
            for val in observed:
                if val in value_to_txn.get(key, {}):
                    writer_tid = value_to_txn[key][val]
                    if writer_tid != reader_tid:
                        wr_edges.add((writer_tid, reader_tid))

    # RW (anti-dependency): reader -> next writer in version order
    for key, order in version_orders.items():
        if not order:
            continue
        val_to_pos = {val: i for i, (val, _tid) in enumerate(order)}

        for reader_tid, observed in reads.get(key, []):
            if not observed:
                first_writer = order[0][1]
                if first_writer != reader_tid:
                    rw_edges.add((reader_tid, first_writer))
            else:
                last_val = observed[-1]
                if last_val in val_to_pos:
                    next_pos = val_to_pos[last_val] + 1
                    if next_pos < len(order):
                        next_writer = order[next_pos][1]
                        if next_writer != reader_tid:
                            rw_edges.add((reader_tid, next_writer))

    # RT: real-time precedence (T1.end < T2.start)
    txn_map = {t['id']: t for t in txns}
    txn_ids = list(txn_map.keys())
    for i in range(len(txn_ids)):
        for j in range(len(txn_ids)):
            if i != j:
                ti = txn_map[txn_ids[i]]
                tj = txn_map[txn_ids[j]]
                if ti['end'] < tj['start']:
                    rt_edges.add((txn_ids[i], txn_ids[j]))

    return ww_edges, wr_edges, rw_edges, rt_edges


# ---------------------------------------------------------------------------
# Graph algorithms
# ---------------------------------------------------------------------------

def has_cycle(edges, node_set):
    """Check if directed graph defined by edges contains a cycle."""
    graph = defaultdict(set)
    for u, v in edges:
        if u in node_set and v in node_set:
            graph[u].add(v)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in node_set}

    def dfs(u):
        color[u] = GRAY
        for v in graph[u]:
            if v not in color:
                continue
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    for n in sorted(node_set):
        if color[n] == WHITE:
            if dfs(n):
                return True
    return False


def find_shortest_cycle(edges, node_set):
    """Find the shortest cycle, breaking ties lexicographically."""
    graph = defaultdict(set)
    for u, v in edges:
        if u in node_set and v in node_set:
            graph[u].add(v)

    shortest = None

    for start in sorted(node_set):
        queue = deque()
        for neighbor in sorted(graph[start]):
            queue.append((neighbor, [start, neighbor]))
        visited = {start: 0}

        while queue:
            curr, path = queue.popleft()
            if curr == start:
                cycle = path
                if shortest is None or len(cycle) < len(shortest):
                    shortest = cycle
                elif len(cycle) == len(shortest) and cycle < shortest:
                    shortest = cycle
                continue

            if curr in visited and visited[curr] <= len(path) - 1:
                continue
            visited[curr] = len(path) - 1

            if shortest and len(path) >= len(shortest):
                continue

            for neighbor in sorted(graph[curr]):
                queue.append((neighbor, path + [neighbor]))

    return shortest


def find_sccs(edges, node_set):
    """Tarjan's algorithm for finding strongly connected components."""
    graph = defaultdict(set)
    for u, v in edges:
        if u in node_set and v in node_set:
            graph[u].add(v)

    index_counter = [0]
    stack = []
    lowlinks = {}
    index = {}
    on_stack = {}
    sccs = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        on_stack[v] = True
        stack.append(v)

        for w in sorted(graph[v]):
            if w not in node_set:
                continue
            if w not in index:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w, False):
                lowlinks[v] = min(lowlinks[v], index[w])

        if lowlinks[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            sccs.append(sorted(scc))

    for v in sorted(node_set):
        if v not in index:
            strongconnect(v)

    return sccs


def min_feedback_vertex_set(edges, node_set):
    """
    Compute the minimum feedback vertex set: smallest set of nodes whose
    removal eliminates all cycles. Brute-force over SCC member subsets.
    """
    sccs = find_sccs(edges, node_set)
    cycle_nodes = set()
    for scc in sccs:
        if len(scc) > 1:
            cycle_nodes.update(scc)

    if not cycle_nodes:
        return []

    cycle_nodes_sorted = sorted(cycle_nodes)

    for size in range(1, len(cycle_nodes_sorted) + 1):
        for combo in combinations(cycle_nodes_sorted, size):
            remaining = node_set - set(combo)
            remaining_edges = {(u, v) for u, v in edges
                               if u in remaining and v in remaining}
            if not has_cycle(remaining_edges, remaining):
                return sorted(combo)

    return sorted(cycle_nodes)


# ---------------------------------------------------------------------------
# Graphviz visualization
# ---------------------------------------------------------------------------

def classify_edge(edge, ww, wr, rw):
    """Return a label string for an edge based on its dependency type(s)."""
    labels = []
    if edge in ww:
        labels.append('ww')
    if edge in wr:
        labels.append('wr')
    if edge in rw:
        labels.append('rw')
    return '+'.join(labels) if labels else '?'


def generate_dot(cycle, ww, wr, rw, history_name):
    """Generate graphviz DOT source for an anomaly cycle."""
    lines = [
        f'digraph {history_name}_anomaly {{',
        '  rankdir=LR;',
        '  node [shape=box style=filled fillcolor=lightyellow];',
    ]

    nodes = set()
    for i in range(len(cycle) - 1):
        nodes.add(cycle[i])

    for node in sorted(nodes):
        lines.append(f'  T{node} [label="T{node}"];')

    for i in range(len(cycle) - 1):
        u, v = cycle[i], cycle[i + 1]
        label = classify_edge((u, v), ww, wr, rw)
        if 'rw' in label:
            color = 'red'
        elif 'wr' in label:
            color = 'blue'
        elif 'ww' in label:
            color = 'darkgreen'
        else:
            color = 'gray'
        lines.append(
            f'  T{u} -> T{v} [label="{label}" color={color} penwidth=2.0];'
        )

    lines.append('}')
    return '\n'.join(lines)


def render_svg(dot_content, output_path):
    """Render DOT content to SVG using graphviz dot command."""
    dot_path = output_path.with_suffix('.dot')
    with open(dot_path, 'w') as f:
        f.write(dot_content)
    subprocess.run(
        ['dot', '-Tsvg', '-o', str(output_path), str(dot_path)],
        check=True,
    )


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze_history(history_data):
    """Analyze a Jepsen history and return full analysis results."""
    txns = extract_committed_transactions(history_data)

    if not txns:
        return {
            'committed_count': 0,
            'consistency_level': 'strict-serializable',
            'g0': False, 'g1c': False, 'g2': False,
            'strict_serializable': True,
            'edge_counts': {'ww': 0, 'wr': 0, 'rw': 0},
            'shortest_cycle': None,
            'scc_count': 0,
            'scc_max_size': 0,
            'min_removal_count': 0,
            'min_removal_set': [],
        }, None, None, None, None

    _appends, reads, value_to_txn = extract_ops(txns)
    version_orders = build_version_order(reads, value_to_txn)
    ww, wr, rw, rt = build_edges(txns, reads, value_to_txn, version_orders)

    node_set = {t['id'] for t in txns}

    g0 = has_cycle(ww, node_set.copy())
    g1c = has_cycle(ww | wr, node_set.copy())
    g2 = has_cycle(ww | wr | rw, node_set.copy())
    not_strict = has_cycle(ww | wr | rw | rt, node_set.copy())

    if not not_strict:
        level = 'strict-serializable'
    elif not g2:
        level = 'serializable'
    elif not g1c:
        level = 'read-committed'
    elif not g0:
        level = 'read-uncommitted'
    else:
        level = 'anomalous'

    # Find shortest anomaly cycle in the relevant graph
    cycle = None
    if g0:
        cycle = find_shortest_cycle(ww, node_set)
    elif g1c:
        cycle = find_shortest_cycle(ww | wr, node_set)
    elif g2:
        cycle = find_shortest_cycle(ww | wr | rw, node_set)

    # SCC analysis on WW+WR+RW graph
    combined = ww | wr | rw
    sccs = find_sccs(combined, node_set)
    nontrivial_sccs = [s for s in sccs if len(s) > 1]

    # Minimum feedback vertex set
    if g2 or g1c or g0:
        mfvs = min_feedback_vertex_set(combined, node_set)
    else:
        mfvs = []

    result = {
        'committed_count': len(txns),
        'consistency_level': level,
        'g0': g0, 'g1c': g1c, 'g2': g2,
        'strict_serializable': not not_strict,
        'edge_counts': {
            'ww': len(ww),
            'wr': len(wr),
            'rw': len(rw),
        },
        'shortest_cycle': cycle,
        'scc_count': len(nontrivial_sccs),
        'scc_max_size': max((len(s) for s in nontrivial_sccs), default=0),
        'min_removal_count': len(mfvs),
        'min_removal_set': mfvs,
    }

    return result, cycle, ww, wr, rw


def main():
    histories_dir = Path('/app/histories')
    graphs_dir = Path('/app/graphs')
    graphs_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    for hist_file in sorted(histories_dir.glob('*.edn')):
        name = hist_file.stem
        print(f"Analyzing {name}...")

        history_data = parse_edn_history(hist_file)
        result, cycle, ww, wr, rw = analyze_history(history_data)
        results[name] = result

        if cycle and (result['g0'] or result['g1c'] or result['g2']):
            dot = generate_dot(
                cycle, ww or set(), wr or set(), rw or set(), name
            )
            svg_path = graphs_dir / f'{name}.svg'
            render_svg(dot, svg_path)
            print(f"  Graph: {svg_path}")

        print(f"  Level: {result['consistency_level']}")
        print(f"  Edges: ww={result['edge_counts']['ww']} "
              f"wr={result['edge_counts']['wr']} "
              f"rw={result['edge_counts']['rw']}")
        print(f"  SCCs: count={result['scc_count']} "
              f"max_size={result['scc_max_size']}")
        if cycle:
            print(f"  Cycle: {cycle}")
        if result['min_removal_set']:
            print(f"  Min removal: {result['min_removal_set']}")

    output_path = Path('/app/results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {output_path}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Star Tree Index — pre-aggregation data structure for OLAP-style analytics.

Each level of the tree corresponds to one dimension. Star nodes ('*') at each
level aggregate across all values, enabling fast unconstrained-dimension queries.
AVG is decomposed into SUM + COUNT for correct merge semantics.
"""

import csv
import json
from collections import defaultdict
from typing import Dict, List, Optional

STAR = '*'


class _MetricAgg:
    """Running aggregation state for one metric: tracks sum, count, min, max."""

    __slots__ = ('sum_val', 'count', 'min_val', 'max_val')

    def __init__(self):
        self.sum_val = 0.0
        self.count = 0
        self.min_val = float('inf')
        self.max_val = float('-inf')

    def add(self, v: float):
        self.sum_val += v
        self.count += 1
        if v < self.min_val:
            self.min_val = v
        if v > self.max_val:
            self.max_val = v

    def merge(self, other: '_MetricAgg'):
        self.sum_val += other.sum_val
        self.count += other.count
        if other.min_val < self.min_val:
            self.min_val = other.min_val
        if other.max_val > self.max_val:
            self.max_val = other.max_val

    def result(self, agg_type: str) -> Optional[float]:
        if self.count == 0:
            return None
        if agg_type == 'SUM':
            return self.sum_val
        if agg_type == 'COUNT':
            return float(self.count)
        if agg_type == 'MIN':
            return self.min_val
        if agg_type == 'MAX':
            return self.max_val
        if agg_type == 'AVG':
            return self.sum_val / self.count
        raise ValueError(f"Unknown agg type: {agg_type}")

    def copy(self) -> '_MetricAgg':
        c = _MetricAgg()
        c.sum_val = self.sum_val
        c.count = self.count
        c.min_val = self.min_val
        c.max_val = self.max_val
        return c


class StarTreeNode:
    """Node in a star tree index."""

    def __init__(self, dimension_index: int = -1, dimension_value: str = None):
        self.dimension_index: int = dimension_index
        self.dimension_value: str = dimension_value
        self.children: Dict[str, 'StarTreeNode'] = {}
        self.aggregations: Dict[str, _MetricAgg] = {}
        self.document_count: int = 0

    def is_leaf(self) -> bool:
        return len(self.children) == 0


class StarTreeBuilder:
    """Builds a star tree from raw records."""

    def __init__(self, config: dict):
        self.dimensions: List[str] = config['dimensions']
        self.metrics: Dict[str, List[str]] = config['metrics']
        self.max_leaf: int = config.get('max_leaf_documents', 100)
        self.star_thresh: int = config.get('star_node_creation_threshold', 3)
        self._root: Optional[StarTreeNode] = None

    def build(self, data: List[dict]) -> StarTreeNode:
        self._root = StarTreeNode(-1, 'ROOT')
        self._build(self._root, data, 0)
        return self._root

    def get_tree(self) -> StarTreeNode:
        return self._root

    def _agg(self, node: StarTreeNode, data: List[dict]):
        node.document_count = len(data)
        for mname in self.metrics:
            a = _MetricAgg()
            for r in data:
                a.add(float(r[mname]))
            node.aggregations[mname] = a

    def _build(self, node: StarTreeNode, data: List[dict], di: int):
        self._agg(node, data)
        if di >= len(self.dimensions) or len(data) <= self.max_leaf:
            return
        dim = self.dimensions[di]
        parts: Dict[str, List[dict]] = defaultdict(list)
        for r in data:
            parts[r[dim]].append(r)
        for val, part in parts.items():
            child = StarTreeNode(di, val)
            node.children[val] = child
            self._build(child, part, di + 1)
        if len(parts) >= self.star_thresh:
            star = StarTreeNode(di, STAR)
            node.children[STAR] = star
            self._build(star, data, di + 1)


class StarTreeQueryEngine:
    """Answers point and group-by aggregation queries on a star tree."""

    def __init__(self, root: StarTreeNode, config: dict):
        self.root = root
        self.dims: List[str] = config['dimensions']
        self.metrics: Dict[str, List[str]] = config['metrics']

    # ----- point query -----

    def query(self, constraints: Dict[str, str], metric: str,
              agg_type: str) -> Optional[float]:
        if metric not in self.metrics:
            raise ValueError(f"Unknown metric: {metric}")
        if agg_type not in self.metrics[metric]:
            raise ValueError(f"Agg '{agg_type}' not in config for '{metric}'")
        collected: List[_MetricAgg] = []
        self._pt(self.root, constraints, metric, 0, collected)
        if not collected:
            return None
        combined = _MetricAgg()
        for a in collected:
            combined.merge(a)
        return combined.result(agg_type)

    def _pt(self, node: StarTreeNode, cons: dict, metric: str,
            di: int, out: list):
        if node.is_leaf() or di >= len(self.dims):
            a = node.aggregations.get(metric)
            if a and a.count > 0:
                out.append(a.copy())
            return
        dim = self.dims[di]
        if dim in cons:
            v = cons[dim]
            if v in node.children:
                self._pt(node.children[v], cons, metric, di + 1, out)
        else:
            if STAR in node.children:
                self._pt(node.children[STAR], cons, metric, di + 1, out)
            else:
                for k, ch in node.children.items():
                    if k != STAR:
                        self._pt(ch, cons, metric, di + 1, out)

    # ----- group-by query -----

    def group_by_query(self, constraints: Dict[str, str],
                       group_by_dimension: str, metric: str,
                       agg_type: str) -> Dict[str, float]:
        if metric not in self.metrics:
            raise ValueError(f"Unknown metric: {metric}")
        if agg_type not in self.metrics[metric]:
            raise ValueError(f"Agg '{agg_type}' not in config for '{metric}'")
        if group_by_dimension not in self.dims:
            raise ValueError(f"Unknown dimension: {group_by_dimension}")
        groups: Dict[str, List[_MetricAgg]] = defaultdict(list)
        self._gb(self.root, constraints, group_by_dimension, metric,
                 0, None, groups)
        result: Dict[str, float] = {}
        for val, alist in groups.items():
            c = _MetricAgg()
            for a in alist:
                c.merge(a)
            r = c.result(agg_type)
            if r is not None:
                result[val] = r
        return result

    def _gb(self, node: StarTreeNode, cons: dict, gb_dim: str,
            metric: str, di: int, gb_val: Optional[str], groups: dict):
        if node.is_leaf() or di >= len(self.dims):
            if gb_val is not None:
                a = node.aggregations.get(metric)
                if a and a.count > 0:
                    groups[gb_val].append(a.copy())
            return
        dim = self.dims[di]
        if dim == gb_dim:
            for k, ch in node.children.items():
                if k != STAR:
                    self._gb(ch, cons, gb_dim, metric, di + 1, k, groups)
        elif dim in cons:
            v = cons[dim]
            if v in node.children:
                self._gb(node.children[v], cons, gb_dim, metric,
                         di + 1, gb_val, groups)
        else:
            if STAR in node.children:
                self._gb(node.children[STAR], cons, gb_dim, metric,
                         di + 1, gb_val, groups)
            else:
                for k, ch in node.children.items():
                    if k != STAR:
                        self._gb(ch, cons, gb_dim, metric,
                                 di + 1, gb_val, groups)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def _deep_clone(node: StarTreeNode) -> StarTreeNode:
    c = StarTreeNode(node.dimension_index, node.dimension_value)
    c.document_count = node.document_count
    for mn, ag in node.aggregations.items():
        c.aggregations[mn] = ag.copy()
    for k, ch in node.children.items():
        c.children[k] = _deep_clone(ch)
    return c


def merge_star_trees(tree_a: StarTreeNode, tree_b: StarTreeNode,
                     config: dict) -> StarTreeNode:
    dims = config['dimensions']
    metrics = config['metrics']
    thresh = config.get('star_node_creation_threshold', 3)
    return _mrg(tree_a, tree_b, dims, metrics, thresh, 0)


def _mrg(a: Optional[StarTreeNode], b: Optional[StarTreeNode],
         dims: list, metrics: dict, thresh: int, di: int) -> Optional[StarTreeNode]:
    if a is None and b is None:
        return None
    if a is None:
        return _deep_clone(b)
    if b is None:
        return _deep_clone(a)

    m = StarTreeNode(a.dimension_index, a.dimension_value)
    m.document_count = a.document_count + b.document_count
    for mn in metrics:
        ag = _MetricAgg()
        if mn in a.aggregations:
            ag.merge(a.aggregations[mn])
        if mn in b.aggregations:
            ag.merge(b.aggregations[mn])
        m.aggregations[mn] = ag

    if di >= len(dims):
        return m

    # merge non-star children
    keys = set()
    for k in a.children:
        if k != STAR:
            keys.add(k)
    for k in b.children:
        if k != STAR:
            keys.add(k)
    for k in keys:
        ca = a.children.get(k)
        cb = b.children.get(k)
        mc = _mrg(ca, cb, dims, metrics, thresh, di + 1)
        if mc is not None:
            m.children[k] = mc

    # rebuild star node
    if len(keys) >= thresh:
        star = StarTreeNode(di, STAR)
        star.document_count = m.document_count
        for mn in metrics:
            star.aggregations[mn] = m.aggregations[mn].copy()
        if di + 1 < len(dims):
            nxt: Dict[str, List[StarTreeNode]] = defaultdict(list)
            for k, ch in m.children.items():
                if k != STAR:
                    for ck, cv in ch.children.items():
                        nxt[ck].append(cv)
            for ck, nodes in nxt.items():
                result = _deep_clone(nodes[0])
                for n in nodes[1:]:
                    result = _mrg(result, n, dims, metrics, thresh, di + 2)
                star.children[ck] = result
        m.children[STAR] = star

    return m

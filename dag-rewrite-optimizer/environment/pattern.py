"""
Pattern matching and graph rewrite framework for DAG optimization.

Inspired by tinygrad's UPat/PatternMatcher system, this module provides:
  - Pat: match a node by op and recursively match its sources
  - Var: match any node and capture it by name
  - CVar: match any CONST node and capture its value by name
  - match(): try to match a pattern against a DAG node
  - graph_rewrite(): apply rewrite rules to a DAG until fixed point

"""
from __future__ import annotations
from dag_ir import DAG, Op


class Var:
    """Match any node and bind its node-ID to *name*.

    If *name* was already captured in the same match, the candidate
    node-ID must equal the previously captured one (equality check).
    """
    def __init__(self, name: str):
        self.name = name


class CVar:
    """Match any CONST node and bind its *value* (not node-ID) to *name*.

    If *name* was already captured, the candidate constant value must
    match exactly.
    """
    def __init__(self, name: str):
        self.name = name


class Pat:
    """Match a node whose op is *op* and whose sources match *srcs*.

    Optionally capture the matched node-ID under *name*.
    """
    def __init__(self, op: Op, *srcs, name: str | None = None):
        self.op = op
        self.srcs = srcs
        self.name = name


def match(dag: DAG, node_id: int, pattern, captures: dict) -> bool:
    """Try to match *pattern* against DAG node *node_id*.

    On success, fills *captures* and returns True.
    On failure, *captures* may be partially filled (caller should
    pass a fresh dict or snapshot+restore as needed).
    """
    if node_id not in dag.nodes:
        return False
    node = dag.nodes[node_id]

    if isinstance(pattern, Var):
        if pattern.name in captures:
            return captures[pattern.name] == node_id
        captures[pattern.name] = node_id
        return True

    if isinstance(pattern, CVar):
        if node.op != Op.CONST:
            return False
        if pattern.name in captures:
            return captures[pattern.name] == node.arg
        captures[pattern.name] = node.arg
        return True

    if isinstance(pattern, Pat):
        if node.op != pattern.op:
            return False
        if len(node.srcs) != len(pattern.srcs):
            return False
        for src_id, src_pat in zip(node.srcs, pattern.srcs):
            if not match(dag, src_id, src_pat, captures):
                return False
        if pattern.name is not None:
            captures[pattern.name] = node_id
        return True

    return False


def graph_rewrite(dag: DAG, rules: list[tuple], max_iters: int = 2000) -> DAG:
    """Apply rewrite rules to *dag* until no rule fires (fixed point).

    Each element of *rules* is a ``(pattern, replacement_fn)`` pair:

    * **pattern** — a tree of ``Pat`` / ``Var`` / ``CVar`` describing the
      sub-graph to recognise.
    * **replacement_fn** — ``callable(dag, captures) -> int | None``.
      Receives the current DAG and the captured bindings.  Must return
      the node-ID that should replace the matched root, or ``None`` to
      skip this match.  The function may create new nodes in *dag*
      (e.g. ``dag.const(42)``) and return their IDs.

    Processing order: nodes are visited in reverse-topological order
    (outputs first) so that outer patterns are attempted before inner
    ones.  On the first successful substitution the scan restarts.

    Returns a compacted DAG with unreachable nodes removed.
    """
    for _ in range(max_iters):
        changed = False
        for nid in reversed(dag.toposort()):
            if nid not in dag.nodes:
                continue
            for pattern, replacement_fn in rules:
                captures: dict = {}
                if match(dag, nid, pattern, captures):
                    result = replacement_fn(dag, captures)
                    if result is not None and result != nid:
                        dag = dag.substitute(nid, result)
                        changed = True
                        break
            if changed:
                break
        if not changed:
            break
    return dag.compact()

#!/usr/bin/env python3
"""Create the circuit analysis module."""


code = '''\
"""Circuit analysis functions for miniHDL."""

from hdl import Wire, Bus


def count_gates(outputs):
    """Count unique logic gates (AND, OR, XOR, NOT) reachable from outputs.

    Constants and primary inputs are not counted.
    """
    visited = set()
    count = 0

    def visit(w):
        nonlocal count
        if w.id in visited:
            return
        visited.add(w.id)
        if w.driver is None:
            return
        op, args = w.driver
        if op == 'CONST':
            return
        count += 1
        for a in args:
            visit(a)

    wires = outputs.wires if isinstance(outputs, Bus) else outputs
    if isinstance(wires, Wire):
        wires = [wires]
    for w in wires:
        visit(w)
    return count


def critical_path(outputs):
    """Compute longest dependency chain (gate delays) from inputs to outputs.

    Primary inputs and constants have depth 0. Each gate adds 1.
    """
    memo = {}

    def depth(w):
        if w.id in memo:
            return memo[w.id]
        if w.driver is None:
            memo[w.id] = 0
            return 0
        op, args = w.driver
        if op == 'CONST':
            memo[w.id] = 0
            return 0
        d = 1 + max((depth(a) for a in args), default=0)
        memo[w.id] = d
        return d

    wires = outputs.wires if isinstance(outputs, Bus) else outputs
    if isinstance(wires, Wire):
        wires = [wires]
    return max(depth(w) for w in wires)


def max_fanout(outputs):
    """Maximum number of gate inputs driven by any single wire.

    Traverses the circuit reachable from outputs, builds a forward
    adjacency count, and returns the highest fanout value.
    """
    visited = set()
    all_wires = []

    def collect(w):
        if w.id in visited:
            return
        visited.add(w.id)
        all_wires.append(w)
        if w.driver is not None and w.driver[0] != 'CONST':
            for a in w.driver[1]:
                collect(a)

    wires = outputs.wires if isinstance(outputs, Bus) else outputs
    if isinstance(wires, Wire):
        wires = [wires]
    for w in wires:
        collect(w)

    fanout = {}
    for w in all_wires:
        if w.driver is not None and w.driver[0] != 'CONST':
            for a in w.driver[1]:
                fanout[a.id] = fanout.get(a.id, 0) + 1

    return max(fanout.values()) if fanout else 0
'''

with open('/app/analysis.py', 'w') as f:
    f.write(code)

print("Created analysis.py")

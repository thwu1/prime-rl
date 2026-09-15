#!/usr/bin/env python3
"""
LALR(1) Parser Generator and Driver.

Reads a context-free grammar in CFG format, constructs the LALR(1) parse
table via the LR(1)-then-merge-by-core approach, and uses the table to
shift-reduce parse an input token sequence.
"""

import sys
from collections import defaultdict

END_MARKER = "$"


# ── Grammar reading ────────────────────────────────────────────────────────

def read_cfg(filename):
    with open(filename) as f:
        lines = []
        for line in f:
            stripped = line.rstrip("\n")
            # skip fully blank lines
            if stripped.strip() == "":
                continue
            lines.append(stripped)

    idx = 0

    num_terminals = int(lines[idx]); idx += 1
    terminals = []
    for _ in range(num_terminals):
        terminals.append(lines[idx].strip()); idx += 1

    num_nonterminals = int(lines[idx]); idx += 1
    nonterminals = []
    for _ in range(num_nonterminals):
        nonterminals.append(lines[idx].strip()); idx += 1

    start_symbol = lines[idx].strip(); idx += 1

    num_productions = int(lines[idx]); idx += 1
    productions = []
    for _ in range(num_productions):
        parts = lines[idx].split()
        idx += 1
        lhs = parts[0]
        rhs = tuple(parts[1:])
        productions.append((lhs, rhs))

    return frozenset(terminals), frozenset(nonterminals), start_symbol, productions


# ── NULLABLE / FIRST ───────────────────────────────────────────────────────

def compute_nullable(productions, nonterminals):
    nullable = set()
    changed = True
    while changed:
        changed = False
        for lhs, rhs in productions:
            if lhs not in nullable and all(s in nullable for s in rhs):
                nullable.add(lhs)
                changed = True
    return nullable


def compute_first(productions, terminals, nullable):
    first = defaultdict(set)
    for t in terminals:
        first[t].add(t)
    first[END_MARKER].add(END_MARKER)

    changed = True
    while changed:
        changed = False
        for lhs, rhs in productions:
            for sym in rhs:
                before = len(first[lhs])
                first[lhs] |= first[sym]
                if len(first[lhs]) > before:
                    changed = True
                if sym not in nullable:
                    break
    return first


def first_of_string(symbols, first, nullable):
    result = set()
    for s in symbols:
        result |= first[s]
        if s not in nullable:
            break
    return result


# ── LR(1) automaton ───────────────────────────────────────────────────────

def build_lr1_automaton(terminals, nonterminals, productions, first, nullable):
    """Build the full LR(1) automaton (states + transitions)."""

    def closure(items):
        result = set(items)
        worklist = list(items)
        while worklist:
            pi, dot, la = worklist.pop()
            _lhs, rhs = productions[pi]
            if dot < len(rhs):
                B = rhs[dot]
                if B in nonterminals:
                    beta_la = list(rhs[dot + 1:]) + [la]
                    lookaheads = first_of_string(beta_la, first, nullable)
                    for i, (plhs, _prhs) in enumerate(productions):
                        if plhs == B:
                            for new_la in lookaheads:
                                item = (i, 0, new_la)
                                if item not in result:
                                    result.add(item)
                                    worklist.append(item)
        return frozenset(result)

    def goto_set(items, symbol):
        kernel = set()
        for pi, dot, la in items:
            _lhs, rhs = productions[pi]
            if dot < len(rhs) and rhs[dot] == symbol:
                kernel.add((pi, dot + 1, la))
        return closure(frozenset(kernel)) if kernel else frozenset()

    initial = closure(frozenset([(0, 0, END_MARKER)]))
    states = [initial]
    state_map = {initial: 0}
    transitions = {}

    worklist = [0]
    while worklist:
        si = worklist.pop(0)
        state = states[si]

        symbols_at_dot = set()
        for pi, dot, _la in state:
            _lhs, rhs = productions[pi]
            if dot < len(rhs):
                symbols_at_dot.add(rhs[dot])

        for sym in symbols_at_dot:
            ns = goto_set(state, sym)
            if ns and ns not in state_map:
                nsi = len(states)
                states.append(ns)
                state_map[ns] = nsi
                worklist.append(nsi)
            if ns:
                transitions[(si, sym)] = state_map[ns]

    return states, transitions


# ── LALR(1) merge ─────────────────────────────────────────────────────────

def merge_to_lalr(states, transitions, terminals, nonterminals, productions):
    """Merge LR(1) states by core to produce LALR(1) states."""

    def get_core(state):
        return frozenset((pi, dot) for pi, dot, _la in state)

    core_to_lalr = {}
    lr1_to_lalr = {}
    lalr_states = []

    for i, state in enumerate(states):
        c = get_core(state)
        if c in core_to_lalr:
            li = core_to_lalr[c]
            lalr_states[li] = lalr_states[li] | state
            lr1_to_lalr[i] = li
        else:
            li = len(lalr_states)
            core_to_lalr[c] = li
            lalr_states.append(set(state))
            lr1_to_lalr[i] = li

    lalr_transitions = {}
    for (src, sym), dst in transitions.items():
        lalr_transitions[(lr1_to_lalr[src], sym)] = lr1_to_lalr[dst]

    return lalr_states, lalr_transitions


# ── Parse table ───────────────────────────────────────────────────────────

def build_parse_table(lalr_states, lalr_transitions, terminals, nonterminals,
                      productions):
    action = {}
    goto_table = {}

    for i, state in enumerate(lalr_states):
        for pi, dot, la in state:
            lhs, rhs = productions[pi]

            if dot < len(rhs):
                sym = rhs[dot]
                if sym in terminals:
                    ns = lalr_transitions.get((i, sym))
                    if ns is not None:
                        key = (i, sym)
                        existing = action.get(key)
                        if existing is None:
                            action[key] = ("shift", ns)
                        elif existing[0] == "reduce":
                            # shift-reduce conflict: prefer shift
                            action[key] = ("shift", ns)
            else:
                # dot at end → reduce or accept
                if pi == 0:
                    action[(i, la)] = ("accept",)
                else:
                    key = (i, la)
                    if key not in action:
                        action[key] = ("reduce", pi)
                    # existing shift wins over reduce (shift-reduce)

        for sym in nonterminals:
            ns = lalr_transitions.get((i, sym))
            if ns is not None:
                goto_table[(i, sym)] = ns

    return action, goto_table


# ── Shift-reduce driver ──────────────────────────────────────────────────

def parse(action, goto_table, productions, tokens):
    stack = [0]
    pos = 0
    n = len(tokens)

    while True:
        state = stack[-1]
        token = tokens[pos] if pos < n else END_MARKER

        act = action.get((state, token))
        if act is None:
            return False

        if act[0] == "shift":
            stack.append(act[1])
            pos += 1
        elif act[0] == "reduce":
            pi = act[1]
            lhs, rhs = productions[pi]
            for _ in range(len(rhs)):
                stack.pop()
            top = stack[-1]
            ns = goto_table.get((top, lhs))
            if ns is None:
                return False
            stack.append(ns)
        elif act[0] == "accept":
            return True
        else:
            return False


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <grammar.cfg> <input.tokens>",
              file=sys.stderr)
        sys.exit(1)

    grammar_file = sys.argv[1]
    input_file = sys.argv[2]

    terminals, nonterminals, _start, productions = read_cfg(grammar_file)

    nullable = compute_nullable(productions, nonterminals)
    first = compute_first(productions, terminals, nullable)

    lr1_states, lr1_transitions = build_lr1_automaton(
        terminals, nonterminals, productions, first, nullable
    )

    lalr_states, lalr_transitions = merge_to_lalr(
        lr1_states, lr1_transitions, terminals, nonterminals, productions
    )

    action, goto_table = build_parse_table(
        lalr_states, lalr_transitions, terminals, nonterminals, productions
    )

    with open(input_file) as f:
        tokens = f.read().split()

    result = parse(action, goto_table, productions, tokens)
    print("accept" if result else "reject")


if __name__ == "__main__":
    main()

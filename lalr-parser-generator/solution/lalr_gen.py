#!/usr/bin/env python3
"""LALR(1) parser generator: reads a CFG file, emits a standalone C parser to stdout."""

import sys
from collections import defaultdict

END = "$"


def read_cfg(path):
    with open(path) as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    i = 0
    nt = int(lines[i]); i += 1
    terms = [lines[i + j].strip() for j in range(nt)]; i += nt
    nn = int(lines[i]); i += 1
    nonterms = [lines[i + j].strip() for j in range(nn)]; i += nn
    start = lines[i].strip(); i += 1
    np = int(lines[i]); i += 1
    prods = []
    for _ in range(np):
        p = lines[i].split(); i += 1
        prods.append((p[0], tuple(p[1:])))
    return terms, nonterms, start, prods


def compute_nullable(prods, ntset):
    nul = set()
    changed = True
    while changed:
        changed = False
        for lhs, rhs in prods:
            if lhs not in nul and all(s in nul for s in rhs):
                nul.add(lhs)
                changed = True
    return nul


def compute_first(prods, tset, nul):
    first = defaultdict(set)
    for t in tset:
        first[t].add(t)
    first[END].add(END)
    changed = True
    while changed:
        changed = False
        for lhs, rhs in prods:
            for sym in rhs:
                before = len(first[lhs])
                first[lhs] |= first[sym]
                if len(first[lhs]) > before:
                    changed = True
                if sym not in nul:
                    break
    return first


def first_of_string(syms, first, nul):
    result = set()
    for s in syms:
        result |= first[s]
        if s not in nul:
            break
    return result


def build_lr1(tset, ntset, prods, first, nul):
    def closure(items):
        res = set(items)
        wl = list(items)
        while wl:
            pi, dot, la = wl.pop()
            _, rhs = prods[pi]
            if dot < len(rhs) and rhs[dot] in ntset:
                B = rhs[dot]
                beta_la = list(rhs[dot + 1:]) + [la]
                las = first_of_string(beta_la, first, nul)
                for j, (plhs, _) in enumerate(prods):
                    if plhs == B:
                        for nl in las:
                            item = (j, 0, nl)
                            if item not in res:
                                res.add(item)
                                wl.append(item)
        return frozenset(res)

    def goto_set(items, sym):
        kernel = set()
        for pi, dot, la in items:
            _, rhs = prods[pi]
            if dot < len(rhs) and rhs[dot] == sym:
                kernel.add((pi, dot + 1, la))
        return closure(frozenset(kernel)) if kernel else frozenset()

    s0 = closure(frozenset([(0, 0, END)]))
    states = [s0]
    smap = {s0: 0}
    trans = {}
    wl = [0]
    while wl:
        si = wl.pop(0)
        syms = set()
        for pi, dot, _ in states[si]:
            _, rhs = prods[pi]
            if dot < len(rhs):
                syms.add(rhs[dot])
        for sym in syms:
            ns = goto_set(states[si], sym)
            if ns and ns not in smap:
                ni = len(states)
                states.append(ns)
                smap[ns] = ni
                wl.append(ni)
            if ns:
                trans[(si, sym)] = smap[ns]
    return states, trans


def merge_to_lalr(states, trans):
    def core(s):
        return frozenset((p, d) for p, d, _ in s)

    c2l = {}
    mapping = {}
    lstates = []
    for i, s in enumerate(states):
        c = core(s)
        if c in c2l:
            li = c2l[c]
            lstates[li] = lstates[li] | s
            mapping[i] = li
        else:
            li = len(lstates)
            c2l[c] = li
            lstates.append(set(s))
            mapping[i] = li
    ltrans = {}
    for (src, sym), dst in trans.items():
        ltrans[(mapping[src], sym)] = mapping[dst]
    return lstates, ltrans


def build_tables(lstates, ltrans, tset, prods):
    action = {}
    goto_tbl = {}
    for i, state in enumerate(lstates):
        for pi, dot, la in state:
            _, rhs = prods[pi]
            if dot < len(rhs):
                sym = rhs[dot]
                if sym in tset:
                    ns = ltrans.get((i, sym))
                    if ns is not None:
                        key = (i, sym)
                        if key not in action or action[key][0] == 2:
                            action[key] = (1, ns)  # shift wins over reduce
            else:
                key = (i, la)
                if pi == 0:
                    action[key] = (3, 0)  # accept
                elif key not in action:
                    action[key] = (2, pi)  # reduce
    for (src, sym), dst in ltrans.items():
        if sym not in tset and sym != END:
            goto_tbl[(src, sym)] = dst
    return action, goto_tbl


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def emit_c(terms, nonterms, prods, action, goto_tbl, nstates):
    all_terms = list(terms) + [END]
    ti = {t: i for i, t in enumerate(all_terms)}
    ni = {n: i for i, n in enumerate(nonterms)}
    nt = len(all_terms)
    nn = len(nonterms)
    np = len(prods)
    end_idx = ti[END]

    o = []
    o.append("/* Generated LALR(1) parser */")
    o.append("#include <stdio.h>")
    o.append("#include <string.h>")
    o.append("")
    o.append(f"#define NSTATES {nstates}")
    o.append(f"#define NTERMS {nt}")
    o.append(f"#define NNONTERMS {nn}")
    o.append(f"#define NPRODS {np}")
    o.append("")

    # Terminal names
    tnames = ", ".join(f'"{esc(t)}"' for t in all_terms)
    o.append(f"static const char *tnames[NTERMS] = {{{tnames}}};")
    o.append("")

    # Production LHS (nonterminal index) and RHS length
    plhs = ", ".join(str(ni[lhs]) for lhs, _ in prods)
    prlen = ", ".join(str(len(rhs)) for _, rhs in prods)
    o.append(f"static const int plhs[NPRODS] = {{{plhs}}};")
    o.append(f"static const int prlen[NPRODS] = {{{prlen}}};")
    o.append("")

    # Action type table (0=error, 1=shift, 2=reduce, 3=accept)
    o.append("static const int atyp[NSTATES][NTERMS] = {")
    for s in range(nstates):
        row = ", ".join(str(action.get((s, t), (0, 0))[0]) for t in all_terms)
        o.append(f"    {{{row}}},")
    o.append("};")
    o.append("")

    # Action value table
    o.append("static const int aval[NSTATES][NTERMS] = {")
    for s in range(nstates):
        row = ", ".join(str(action.get((s, t), (0, 0))[1]) for t in all_terms)
        o.append(f"    {{{row}}},")
    o.append("};")
    o.append("")

    # Goto table (-1 = error)
    o.append("static const int gtbl[NSTATES][NNONTERMS] = {")
    for s in range(nstates):
        row = ", ".join(str(goto_tbl.get((s, n), -1)) for n in nonterms)
        o.append(f"    {{{row}}},")
    o.append("};")
    o.append("")

    # find_term function
    o.append("static int find_term(const char *s) {")
    o.append("    int i;")
    o.append("    for (i = 0; i < NTERMS; i++) {")
    o.append("        if (strcmp(tnames[i], s) == 0) return i;")
    o.append("    }")
    o.append("    return -1;")
    o.append("}")
    o.append("")

    # main
    o.append("int main(int argc, char *argv[]) {")
    o.append("    static int toks[65536];")
    o.append("    static int stk[65536];")
    o.append("    int n = 0, sp = 0, pos = 0;")
    o.append("    char buf[256];")
    o.append("    FILE *fp;")
    o.append("")
    o.append("    if (argc != 2) {")
    o.append('        fprintf(stderr, "Usage: %s <tokens>\\n", argv[0]);')
    o.append("        return 1;")
    o.append("    }")
    o.append('    fp = fopen(argv[1], "r");')
    o.append("    if (!fp) {")
    o.append('        fprintf(stderr, "Cannot open %s\\n", argv[1]);')
    o.append("        return 1;")
    o.append("    }")
    o.append('    while (fscanf(fp, "%255s", buf) == 1) {')
    o.append("        int idx = find_term(buf);")
    o.append("        if (idx < 0) {")
    o.append('            puts("reject");')
    o.append("            fclose(fp);")
    o.append("            return 0;")
    o.append("        }")
    o.append("        toks[n++] = idx;")
    o.append("    }")
    o.append("    fclose(fp);")
    o.append(f"    toks[n++] = {end_idx};")
    o.append("    stk[sp++] = 0;")
    o.append("    for (;;) {")
    o.append("        int st = stk[sp - 1];")
    o.append("        int tk = toks[pos];")
    o.append("        int at = atyp[st][tk];")
    o.append("        int av = aval[st][tk];")
    o.append("")
    o.append("        if (at == 1) {")
    o.append("            stk[sp++] = av;")
    o.append("            pos++;")
    o.append("        } else if (at == 2) {")
    o.append("            int rlen = prlen[av];")
    o.append("            int lhs = plhs[av];")
    o.append("            int g;")
    o.append("            sp -= rlen;")
    o.append("            g = gtbl[stk[sp - 1]][lhs];")
    o.append("            if (g < 0) {")
    o.append('                puts("reject");')
    o.append("                return 0;")
    o.append("            }")
    o.append("            stk[sp++] = g;")
    o.append("        } else if (at == 3) {")
    o.append('            puts("accept");')
    o.append("            return 0;")
    o.append("        } else {")
    o.append('            puts("reject");')
    o.append("            return 0;")
    o.append("        }")
    o.append("    }")
    o.append("}")

    return "\n".join(o) + "\n"


def main():
    if len(sys.argv) != 2:
        sys.stderr.write(f"Usage: {sys.argv[0]} <grammar.cfg>\n")
        sys.exit(1)

    terms, nonterms, _start, prods = read_cfg(sys.argv[1])
    tset = frozenset(terms)
    ntset = frozenset(nonterms)

    nul = compute_nullable(prods, ntset)
    first = compute_first(prods, tset, nul)

    lr1_states, lr1_trans = build_lr1(tset, ntset, prods, first, nul)
    lalr_states, lalr_trans = merge_to_lalr(lr1_states, lr1_trans)
    action, goto_tbl = build_tables(lalr_states, lalr_trans, tset, prods)

    sys.stdout.write(emit_c(terms, nonterms, prods, action, goto_tbl, len(lalr_states)))


if __name__ == "__main__":
    main()

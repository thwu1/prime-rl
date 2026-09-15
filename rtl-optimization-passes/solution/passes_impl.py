"""
RTL optimization passes — full implementation.

"""

from rtl import (
    Function, Inop, Iop, Icond, Ireturn,
    deep_copy_function, eval_op, eval_cond,
)

# ============================================================
# Lattice for Sparse Conditional Constant Propagation
# ============================================================

_BOTTOM = ('bottom',)
_TOP = ('top',)


def _make_const(n):
    return ('const', n)


def _is_const(v):
    return isinstance(v, tuple) and len(v) == 2 and v[0] == 'const'


def _get_val(v):
    return v[1]


def _lattice_join(a, b):
    if a == _BOTTOM:
        return b
    if b == _BOTTOM:
        return a
    if a == _TOP or b == _TOP:
        return _TOP
    if a == b:
        return a
    return _TOP


def _join_states(states_list):
    result = {}
    all_regs = set()
    for s in states_list:
        all_regs.update(s.keys())
    for reg in all_regs:
        val = _BOTTOM
        for s in states_list:
            val = _lattice_join(val, s.get(reg, _BOTTOM))
        result[reg] = val
    return result


# ============================================================
# Pass 1: Sparse Conditional Constant Propagation
# ============================================================

def constant_propagation(func):
    func = deep_copy_function(func)

    preds = {n: [] for n in func.code}
    for n, instr in func.code.items():
        for s in instr.successors():
            if s in preds:
                preds[s].append(n)

    out_state = {n: {} for n in func.code}
    exec_edges = set()
    exec_nodes = set()
    entry_base = {p: _TOP for p in func.params}

    worklist = [func.entry]
    exec_nodes.add(func.entry)

    max_iter = len(func.code) * 20 + 100
    iteration = 0

    while worklist and iteration < max_iter:
        iteration += 1
        node = worklist.pop(0)

        if node not in func.code:
            continue

        pred_states = []
        if node == func.entry:
            pred_states.append(entry_base)
        for pred in preds.get(node, []):
            if (pred, node) in exec_edges:
                pred_states.append(out_state[pred])
        if not pred_states:
            continue

        entry = _join_states(pred_states)
        instr = func.code[node]
        new_out = dict(entry)
        new_exec_succs = []

        if isinstance(instr, Inop):
            new_exec_succs = [instr.succ]

        elif isinstance(instr, Iop):
            if instr.op == "const":
                result = _make_const(instr.imm)
            else:
                arg_vals = [entry.get(a, _BOTTOM) for a in instr.args]
                if any(v == _BOTTOM for v in arg_vals):
                    result = _BOTTOM
                elif any(v == _TOP for v in arg_vals):
                    result = _TOP
                else:
                    concrete_args = [_get_val(v) for v in arg_vals]
                    try:
                        result = _make_const(eval_op(instr.op, concrete_args))
                    except Exception:
                        result = _TOP
            new_out[instr.dest] = result
            new_exec_succs = [instr.succ]

        elif isinstance(instr, Icond):
            arg_vals = [entry.get(a, _BOTTOM) for a in instr.args]
            if all(_is_const(v) for v in arg_vals):
                concrete_args = [_get_val(v) for v in arg_vals]
                if eval_cond(instr.cond, concrete_args):
                    new_exec_succs = [instr.ifso]
                else:
                    new_exec_succs = [instr.ifnot]
            elif any(v == _BOTTOM for v in arg_vals):
                new_exec_succs = []
            else:
                new_exec_succs = [instr.ifso, instr.ifnot]

        elif isinstance(instr, Ireturn):
            new_exec_succs = []

        out_changed = (new_out != out_state[node])
        if out_changed:
            out_state[node] = new_out
            for s in instr.successors():
                if (node, s) in exec_edges and s in exec_nodes and s not in worklist:
                    worklist.append(s)

        for s in new_exec_succs:
            if s not in func.code:
                continue
            edge = (node, s)
            if edge not in exec_edges:
                exec_edges.add(edge)
                if s not in exec_nodes:
                    exec_nodes.add(s)
                if s not in worklist:
                    worklist.append(s)

    # Apply transformations
    for node in list(func.code.keys()):
        if node not in exec_nodes:
            continue

        pred_states = []
        if node == func.entry:
            pred_states.append(entry_base)
        for pred in preds.get(node, []):
            if (pred, node) in exec_edges:
                pred_states.append(out_state[pred])
        if not pred_states:
            continue
        entry = _join_states(pred_states)

        instr = func.code[node]

        if isinstance(instr, Iop) and instr.op != "const":
            arg_vals = [entry.get(a, _BOTTOM) for a in instr.args]
            if all(_is_const(v) for v in arg_vals):
                concrete_args = [_get_val(v) for v in arg_vals]
                try:
                    val = eval_op(instr.op, concrete_args)
                    func.code[node] = Iop("const", [], instr.dest,
                                          instr.succ, val)
                except Exception:
                    pass

        elif isinstance(instr, Icond):
            arg_vals = [entry.get(a, _BOTTOM) for a in instr.args]
            if all(_is_const(v) for v in arg_vals):
                concrete_args = [_get_val(v) for v in arg_vals]
                if eval_cond(instr.cond, concrete_args):
                    func.code[node] = Inop(instr.ifso)
                else:
                    func.code[node] = Inop(instr.ifnot)

    return func


# ============================================================
# Pass 2: Dead Code Elimination
# ============================================================

def dead_code_elimination(func):
    func = deep_copy_function(func)

    changed = True
    while changed:
        changed = False

        reachable = func.reachable_nodes()
        for node in list(func.code.keys()):
            if node not in reachable:
                del func.code[node]
                changed = True

        live_in = {n: set() for n in func.code}
        live_out = {n: set() for n in func.code}

        df_changed = True
        while df_changed:
            df_changed = False
            for node in func.code:
                instr = func.code[node]

                new_live_out = set()
                for s in instr.successors():
                    if s in live_in:
                        new_live_out |= live_in[s]

                if isinstance(instr, Iop):
                    if instr.dest in new_live_out:
                        new_live_in = (new_live_out - {instr.dest}) | set(instr.args)
                    else:
                        new_live_in = set(new_live_out)
                elif isinstance(instr, Icond):
                    new_live_in = new_live_out | set(instr.args)
                elif isinstance(instr, Ireturn):
                    new_live_in = set()
                    if instr.arg:
                        new_live_in.add(instr.arg)
                elif isinstance(instr, Inop):
                    new_live_in = set(new_live_out)
                else:
                    new_live_in = set(new_live_out)

                if new_live_out != live_out[node] or new_live_in != live_in[node]:
                    live_out[node] = new_live_out
                    live_in[node] = new_live_in
                    df_changed = True

        for node in list(func.code.keys()):
            instr = func.code[node]
            if isinstance(instr, Iop):
                if instr.dest not in live_out[node]:
                    func.code[node] = Inop(instr.succ)
                    changed = True

    reachable = func.reachable_nodes()
    for node in list(func.code.keys()):
        if node not in reachable:
            del func.code[node]

    return func


# ============================================================
# Pass 3: Branch Tunneling
# ============================================================

def branch_tunneling(func):
    func = deep_copy_function(func)

    def find_target(node, visited=None):
        if visited is None:
            visited = set()
        if node not in func.code:
            return node
        if node in visited:
            return node
        instr = func.code[node]
        if isinstance(instr, Inop):
            visited.add(node)
            return find_target(instr.succ, visited)
        return node

    targets = {}
    for node in func.code:
        targets[node] = find_target(node)

    for node in list(func.code.keys()):
        instr = func.code[node]

        if isinstance(instr, Inop):
            new_succ = targets.get(instr.succ, instr.succ)
            if new_succ != instr.succ:
                func.code[node] = Inop(new_succ)

        elif isinstance(instr, Iop):
            new_succ = targets.get(instr.succ, instr.succ)
            if new_succ != instr.succ:
                func.code[node] = Iop(instr.op, instr.args, instr.dest,
                                      new_succ, instr.imm)

        elif isinstance(instr, Icond):
            new_ifso = targets.get(instr.ifso, instr.ifso)
            new_ifnot = targets.get(instr.ifnot, instr.ifnot)
            if new_ifso != instr.ifso or new_ifnot != instr.ifnot:
                func.code[node] = Icond(instr.cond, instr.args,
                                        new_ifso, new_ifnot)

    return func

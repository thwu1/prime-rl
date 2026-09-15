"""
RTL Optimizer — Multi-pass optimization pipeline.


Implements constant propagation, dead code elimination, and common
subexpression elimination for RTL programs.
"""

import sys
import copy
from collections import deque

sys.path.insert(0, '/app')
from rtl import eval_op, eval_cond


# ========================================================================
# Utilities
# ========================================================================

def get_successors(instr):
    kind = instr["kind"]
    if kind == "nop":
        return [instr["succ"]]
    elif kind == "op":
        return [instr["succ"]]
    elif kind == "cond":
        return [instr["ifso"], instr["ifnot"]]
    elif kind == "ret":
        return []
    return []


def get_used_regs(instr):
    kind = instr["kind"]
    if kind == "op":
        if instr["op"] == "const":
            return []
        return list(instr.get("args", []))
    elif kind == "cond":
        return [instr["arg1"], instr["arg2"]]
    elif kind == "ret":
        return [instr["arg"]]
    return []


def get_defined_reg(instr):
    if instr["kind"] == "op":
        return instr["dst"]
    return None


def compute_reachable(prog):
    code = prog["code"]
    entry = prog["entrypoint"]
    visited = set()
    queue = deque([entry])
    while queue:
        n = queue.popleft()
        if n in visited or n not in code:
            continue
        visited.add(n)
        for s in get_successors(code[n]):
            if s not in visited:
                queue.append(s)
    return visited


def compute_predecessors(prog, reachable=None):
    code = prog["code"]
    if reachable is None:
        reachable = set(code.keys())
    preds = {n: [] for n in reachable if n in code}
    for n in reachable:
        if n not in code:
            continue
        for s in get_successors(code[n]):
            if s in preds:
                preds[s].append(n)
    return preds


def compute_rpo(prog):
    code = prog["code"]
    entry = prog["entrypoint"]
    visited = set()
    postorder = []

    stack = [(entry, False)]
    while stack:
        node, processed = stack.pop()
        if processed:
            postorder.append(node)
            continue
        if node in visited or node not in code:
            continue
        visited.add(node)
        stack.append((node, True))
        for s in reversed(get_successors(code[node])):
            if s not in visited:
                stack.append((s, False))

    return list(reversed(postorder))


def remove_unreachable(prog):
    reachable = compute_reachable(prog)
    new_code = {n: instr for n, instr in prog["code"].items() if n in reachable}
    return {**prog, "code": new_code}


# ========================================================================
# Constant Propagation (Forward Dataflow)
# ========================================================================

BOT = ('bot',)
TOP = ('top',)


def lattice_val(v):
    if v is BOT or v is TOP:
        return v
    return v


def lattice_join(a, b):
    if a is BOT:
        return b
    if b is BOT:
        return a
    if a is TOP or b is TOP:
        return TOP
    if a == b:
        return a
    return TOP


def is_const(v):
    return v is not BOT and v is not TOP


def abstract_eval(op, arg_vals):
    if any(v is BOT for v in arg_vals):
        return BOT
    if all(is_const(v) for v in arg_vals):
        try:
            return eval_op(op, arg_vals)
        except Exception:
            return TOP
    # Strength reductions with partial constants
    if op == "mul":
        for v in arg_vals:
            if is_const(v) and v == 0:
                return 0
    if op == "and":
        for v in arg_vals:
            if is_const(v) and v == 0:
                return 0
    return TOP


def constant_propagation(prog):
    code = prog["code"]
    entry = prog["entrypoint"]

    # State at each node: dict[reg -> abstract_val]
    states = {}
    init = {}
    for p in prog["params"]:
        init[p] = TOP
    states[entry] = dict(init)

    worklist = deque([entry])
    max_iter = len(code) * 50 + 100

    for _ in range(max_iter):
        if not worklist:
            break
        n = worklist.popleft()
        if n not in code:
            continue

        instr = code[n]
        state = dict(states.get(n, {}))

        # Compute output state and successors
        if instr["kind"] == "nop":
            succs_with_state = [(instr["succ"], state)]

        elif instr["kind"] == "op":
            out = dict(state)
            op = instr["op"]
            dst = instr["dst"]
            if op == "const":
                out[dst] = instr["imm"]
            elif op == "move":
                out[dst] = state.get(instr["args"][0], BOT)
            else:
                av = [state.get(r, BOT) for r in instr["args"]]
                out[dst] = abstract_eval(op, av)
            succs_with_state = [(instr["succ"], out)]

        elif instr["kind"] == "cond":
            a = state.get(instr["arg1"], BOT)
            b = state.get(instr["arg2"], BOT)
            if is_const(a) and is_const(b):
                result = eval_cond(instr["cmp"], a, b)
                if result:
                    succs_with_state = [(instr["ifso"], state)]
                else:
                    succs_with_state = [(instr["ifnot"], state)]
            else:
                succs_with_state = [(instr["ifso"], state), (instr["ifnot"], state)]

        elif instr["kind"] == "ret":
            succs_with_state = []
        else:
            succs_with_state = []

        for s, out_state in succs_with_state:
            if s not in states:
                states[s] = dict(out_state)
                worklist.append(s)
            else:
                changed = False
                for r, v in out_state.items():
                    old = states[s].get(r, BOT)
                    new = lattice_join(old, v)
                    if new != old:
                        states[s][r] = new
                        changed = True
                if changed:
                    worklist.append(s)

    # Transform code
    new_code = {}
    for n, instr in code.items():
        if n not in states:
            new_code[n] = instr
            continue

        state = states[n]

        if instr["kind"] == "op" and instr["op"] not in ("const", "move"):
            op = instr["op"]
            args = instr["args"]
            dst = instr["dst"]
            succ = instr["succ"]
            av = [state.get(r, BOT) for r in args]

            if all(is_const(v) for v in av):
                try:
                    result = eval_op(op, av)
                    new_code[n] = {"kind": "op", "op": "const", "imm": result,
                                   "args": [], "dst": dst, "succ": succ}
                    continue
                except Exception:
                    pass

            sr = _strength_reduce(instr, av)
            if sr is not None:
                new_code[n] = sr
                continue

            new_code[n] = instr

        elif instr["kind"] == "cond":
            a = state.get(instr["arg1"], BOT)
            b = state.get(instr["arg2"], BOT)
            if is_const(a) and is_const(b):
                result = eval_cond(instr["cmp"], a, b)
                target = instr["ifso"] if result else instr["ifnot"]
                new_code[n] = {"kind": "nop", "succ": target}
            else:
                new_code[n] = instr
        else:
            new_code[n] = instr

    return {**prog, "code": new_code}


def _strength_reduce(instr, arg_vals):
    op = instr["op"]
    args = instr["args"]
    dst = instr["dst"]
    succ = instr["succ"]

    if op == "mul":
        for i, v in enumerate(arg_vals):
            if is_const(v) and v == 0:
                return {"kind": "op", "op": "const", "imm": 0,
                        "args": [], "dst": dst, "succ": succ}
            if is_const(v) and v == 1:
                other = args[1 - i]
                return {"kind": "op", "op": "move", "args": [other],
                        "dst": dst, "succ": succ}
    elif op == "add":
        for i, v in enumerate(arg_vals):
            if is_const(v) and v == 0:
                other = args[1 - i]
                return {"kind": "op", "op": "move", "args": [other],
                        "dst": dst, "succ": succ}
    elif op == "sub":
        if is_const(arg_vals[1]) and arg_vals[1] == 0:
            return {"kind": "op", "op": "move", "args": [args[0]],
                    "dst": dst, "succ": succ}
    elif op == "and":
        for i, v in enumerate(arg_vals):
            if is_const(v) and v == 0:
                return {"kind": "op", "op": "const", "imm": 0,
                        "args": [], "dst": dst, "succ": succ}
    elif op == "or":
        for i, v in enumerate(arg_vals):
            if is_const(v) and v == 0:
                other = args[1 - i]
                return {"kind": "op", "op": "move", "args": [other],
                        "dst": dst, "succ": succ}

    return None


# ========================================================================
# Dead Code Elimination (Backward Liveness)
# ========================================================================

def dead_code_elimination(prog):
    code = prog["code"]
    reachable = compute_reachable(prog)
    preds = compute_predecessors(prog, reachable)

    # Iterative DCE: identify dead instructions, re-analyze treating them
    # as nops, repeat until the dead set stabilizes.
    dead_nodes = set()

    for _outer in range(20):
        live_in = {n: set() for n in reachable if n in code}
        live_out = {n: set() for n in reachable if n in code}

        worklist = deque(reachable)
        max_iter = len(code) * 50 + 100

        for _ in range(max_iter):
            if not worklist:
                break
            n = worklist.pop()
            if n not in code:
                continue

            instr = code[n]

            new_out = set()
            for s in get_successors(instr):
                if s in live_in:
                    new_out |= live_in[s]

            if n in dead_nodes:
                # Treat dead instruction as nop: passes through liveness
                new_in = set(new_out)
            else:
                new_in = set(new_out)
                d = get_defined_reg(instr)
                if d is not None:
                    new_in.discard(d)
                for r in get_used_regs(instr):
                    new_in.add(r)

            if new_in != live_in.get(n, set()) or new_out != live_out.get(n, set()):
                live_in[n] = new_in
                live_out[n] = new_out
                for p in preds.get(n, []):
                    worklist.append(p)

        new_dead = set()
        for n in reachable:
            if n not in code:
                continue
            instr = code[n]
            if instr["kind"] == "op":
                dst = instr["dst"]
                if dst not in live_out.get(n, set()):
                    new_dead.add(n)

        if new_dead == dead_nodes:
            break
        dead_nodes = new_dead

    new_code = {}
    for n, instr in code.items():
        if n in dead_nodes:
            new_code[n] = {"kind": "nop", "succ": instr["succ"]}
        else:
            new_code[n] = instr

    return {**prog, "code": new_code}


# ========================================================================
# Common Subexpression Elimination (Value Numbering)
# ========================================================================

def common_subexpression_elimination(prog):
    code = prog["code"]
    reachable = compute_reachable(prog)
    preds = compute_predecessors(prog, reachable)
    rpo = compute_rpo(prog)

    new_code = dict(code)
    vn_counter = [0]

    def fresh_vn():
        vn_counter[0] += 1
        return vn_counter[0]

    # Exit numbering: node -> (reg_to_vn, expr_to_vn, vn_to_regs)
    exit_num = {}

    for n in rpo:
        if n not in code or n not in reachable:
            continue

        my_preds = [p for p in preds.get(n, []) if p in reachable and p in exit_num]

        if len(my_preds) == 1:
            prev_r2v, prev_e2v, prev_v2r = exit_num[my_preds[0]]
            reg_to_vn = dict(prev_r2v)
            expr_to_vn = dict(prev_e2v)
            vn_to_regs = {k: list(v) for k, v in prev_v2r.items()}
        else:
            reg_to_vn = {}
            expr_to_vn = {}
            vn_to_regs = {}

        instr = code[n]

        if instr["kind"] == "op":
            dst = instr["dst"]
            op = instr["op"]

            # Forget old VN for dst
            old_vn = reg_to_vn.get(dst)
            if old_vn is not None and old_vn in vn_to_regs:
                vn_to_regs[old_vn] = [r for r in vn_to_regs[old_vn] if r != dst]
            reg_to_vn.pop(dst, None)

            if op == "move":
                src = instr["args"][0]
                vn = reg_to_vn.get(src)
                if vn is None:
                    vn = fresh_vn()
                    reg_to_vn[src] = vn
                    vn_to_regs.setdefault(vn, []).append(src)
                reg_to_vn[dst] = vn
                vn_to_regs.setdefault(vn, []).append(dst)

            elif op == "const":
                imm = instr["imm"]
                expr_key = ("const", (imm,))
                if expr_key in expr_to_vn:
                    result_vn = expr_to_vn[expr_key]
                    candidates = [r for r in vn_to_regs.get(result_vn, []) if r != dst]
                    if candidates:
                        new_code[n] = {"kind": "op", "op": "move",
                                       "args": [candidates[0]], "dst": dst,
                                       "succ": instr["succ"]}
                    reg_to_vn[dst] = result_vn
                    vn_to_regs.setdefault(result_vn, []).append(dst)
                else:
                    result_vn = fresh_vn()
                    expr_to_vn[expr_key] = result_vn
                    reg_to_vn[dst] = result_vn
                    vn_to_regs.setdefault(result_vn, []).append(dst)

            else:
                # Compute VNs for args
                arg_vns = []
                for r in instr["args"]:
                    vn = reg_to_vn.get(r)
                    if vn is None:
                        vn = fresh_vn()
                        reg_to_vn[r] = vn
                        vn_to_regs.setdefault(vn, []).append(r)
                    arg_vns.append(vn)

                expr_key = (op, tuple(arg_vns))

                if expr_key in expr_to_vn:
                    result_vn = expr_to_vn[expr_key]
                    candidates = [r for r in vn_to_regs.get(result_vn, []) if r != dst]
                    if candidates:
                        new_code[n] = {"kind": "op", "op": "move",
                                       "args": [candidates[0]], "dst": dst,
                                       "succ": instr["succ"]}
                    reg_to_vn[dst] = result_vn
                    vn_to_regs.setdefault(result_vn, []).append(dst)
                else:
                    result_vn = fresh_vn()
                    expr_to_vn[expr_key] = result_vn
                    reg_to_vn[dst] = result_vn
                    vn_to_regs.setdefault(result_vn, []).append(dst)

        exit_num[n] = (reg_to_vn, expr_to_vn, vn_to_regs)

    return {**prog, "code": new_code}


# ========================================================================
# Pipeline
# ========================================================================

def optimize(prog):
    prog = copy.deepcopy(prog)
    prog = constant_propagation(prog)
    prog = remove_unreachable(prog)
    prog = dead_code_elimination(prog)
    prog = common_subexpression_elimination(prog)
    prog = dead_code_elimination(prog)
    prog = remove_unreachable(prog)
    return prog

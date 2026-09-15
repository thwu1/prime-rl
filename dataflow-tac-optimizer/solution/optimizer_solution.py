
"""Complete dataflow optimizer for TAC IR."""

import sys
sys.path.insert(0, "/app")

from typing import List, Dict, Set, Optional, Tuple
from tac_parser import Function, Instruction, is_literal, literal_value, emit
from cfg import build_cfg, cfg_to_instructions, CFG, BasicBlock


TOP = "TOP"  # unknown
BOT = "BOT"  # conflicting


def optimize(functions: List[Function]) -> List[Function]:
    """Apply all optimization passes iteratively to each function."""
    result = []
    for func in functions:
        optimized_func = optimize_function(func)
        result.append(optimized_func)
    return result


def optimize_function(func: Function) -> Function:
    """Optimize a single function to fixed point."""
    current = func.clone()
    max_iters = 50
    for _ in range(max_iters):
        prev_text = emit([current])

        current = run_constant_propagation(current)
        current = run_unreachable_elimination(current)
        current = run_cse(current)
        current = run_dce(current)

        new_text = emit([current])
        if new_text == prev_text:
            break

    return current


# ==================== Constant Propagation & Folding ====================

def run_constant_propagation(func: Function) -> Function:
    """Forward constant propagation with folding."""
    func = func.clone()
    body = [i for i in func.body if i.kind not in ("func_start", "func_end")]
    params = [i for i in func.body if i.kind == "param"]
    func_start = next((i for i in func.body if i.kind == "func_start"), None)
    func_end = next((i for i in func.body if i.kind == "func_end"), None)

    cfg = build_cfg([i for i in func.body if i.kind != "param"])

    # Initialize constant lattice: param -> TOP (unknown)
    # Forward analysis: for each block, compute output constant state
    # Lattice: var -> int value (constant) | TOP (unknown) | BOT (never assigned)
    # Meet: same value -> that value, different values -> TOP

    block_ids = sorted(cfg.blocks.keys())
    reachable = cfg.reachable_block_ids()

    # in_state[bid] = dict of var -> value or TOP
    in_state: Dict[int, Dict[str, object]] = {}
    out_state: Dict[int, Dict[str, object]] = {}

    for bid in block_ids:
        in_state[bid] = {}
        out_state[bid] = {}

    # Parameters are TOP (unknown)
    for p in func.params:
        in_state[cfg.entry_id][p] = TOP

    changed = True
    max_iter = 100
    iteration = 0
    while changed and iteration < max_iter:
        changed = False
        iteration += 1
        for bid in block_ids:
            if bid not in reachable:
                continue
            block = cfg.blocks[bid]
            state = dict(in_state[bid])

            for instr in block.instructions:
                _propagate_instr(instr, state)

            if out_state[bid] != state:
                out_state[bid] = state
                changed = True

            # Propagate to successors
            for succ_id in block.successors:
                new_in = _meet_states(in_state[succ_id], state)
                if new_in != in_state[succ_id]:
                    in_state[succ_id] = new_in
                    changed = True

    # Now rewrite instructions using computed constant state
    for bid in block_ids:
        if bid not in reachable:
            continue
        block = cfg.blocks[bid]
        state = dict(in_state[bid])
        new_instrs = []
        for instr in block.instructions:
            rewritten = _rewrite_with_constants(instr, state)
            new_instrs.append(rewritten)
            _propagate_instr(rewritten, state)
        block.instructions = new_instrs

    # Linearize back
    new_body = cfg_to_instructions(cfg, func_start, func_end, params)
    func.body = new_body
    return func


def _propagate_instr(instr: Instruction, state: Dict[str, object]):
    """Update state after executing instr."""
    if instr.kind == "const_load":
        state[instr.dst] = literal_value(instr.src1)
    elif instr.kind == "copy":
        if is_literal(instr.src1):
            state[instr.dst] = literal_value(instr.src1)
        elif instr.src1 in state and state[instr.src1] != TOP:
            state[instr.dst] = state[instr.src1]
        else:
            state[instr.dst] = TOP
    elif instr.kind == "assign_binop":
        v1 = _resolve_const(instr.src1, state)
        v2 = _resolve_const(instr.src2, state)
        if v1 is not None and v2 is not None:
            result = _eval_binop(v1, instr.op, v2)
            state[instr.dst] = result
        else:
            state[instr.dst] = TOP
    elif instr.kind == "assign_unop":
        v1 = _resolve_const(instr.src1, state)
        if v1 is not None:
            result = _eval_unop(instr.op, v1)
            state[instr.dst] = result
        else:
            state[instr.dst] = TOP
    elif instr.kind == "call":
        state[instr.dst] = TOP
    elif instr.kind == "param":
        if instr.src1 not in state:
            state[instr.src1] = TOP


def _resolve_const(var: str, state: Dict[str, object]) -> Optional[int]:
    """Resolve a variable or literal to a constant value, or None if unknown."""
    if is_literal(var):
        return literal_value(var)
    if var in state and state[var] != TOP:
        return state[var]
    return None


def _eval_binop(a: int, op: str, b: int) -> int:
    if op == "+": return a + b
    if op == "-": return a - b
    if op == "*": return a * b
    if op == "/": return a // b if b != 0 else 0
    if op == "%": return a % b if b != 0 else 0
    if op == "==": return 1 if a == b else 0
    if op == "!=": return 1 if a != b else 0
    if op == "<": return 1 if a < b else 0
    if op == ">": return 1 if a > b else 0
    if op == "<=": return 1 if a <= b else 0
    if op == ">=": return 1 if a >= b else 0
    if op == "&&": return 1 if (a and b) else 0
    if op == "||": return 1 if (a or b) else 0
    return 0


def _eval_unop(op: str, a: int) -> int:
    if op == "-": return -a
    if op == "!": return 1 if not a else 0
    return 0


def _meet_states(s1: Dict[str, object], s2: Dict[str, object]) -> Dict[str, object]:
    """Meet two constant states (lattice join)."""
    result = dict(s1)
    for var, val in s2.items():
        if var not in result:
            result[var] = val
        elif result[var] == val:
            pass  # same constant
        else:
            result[var] = TOP  # conflict
    return result


def _rewrite_with_constants(instr: Instruction, state: Dict[str, object]) -> Instruction:
    """Rewrite instruction to use constants where possible, fold if all constant."""
    instr = instr.clone()

    if instr.kind == "assign_binop":
        v1 = _resolve_const(instr.src1, state)
        v2 = _resolve_const(instr.src2, state)
        if v1 is not None and v2 is not None:
            result = _eval_binop(v1, instr.op, v2)
            instr.kind = "const_load"
            instr.src1 = str(result)
            instr.op = None
            instr.src2 = None
        else:
            if v1 is not None:
                instr.src1 = str(v1)
            if v2 is not None:
                instr.src2 = str(v2)

    elif instr.kind == "assign_unop":
        v1 = _resolve_const(instr.src1, state)
        if v1 is not None:
            result = _eval_unop(instr.op, v1)
            instr.kind = "const_load"
            instr.src1 = str(result)
            instr.op = None

    elif instr.kind == "copy":
        v1 = _resolve_const(instr.src1, state)
        if v1 is not None:
            instr.kind = "const_load"
            instr.src1 = str(v1)

    elif instr.kind == "if_goto":
        v1 = _resolve_const(instr.src1, state)
        if v1 is not None:
            if v1:
                instr.kind = "goto"
                instr.src1 = None
            else:
                # Condition is always false — this IF never jumps
                # Replace with a no-op label (will be cleaned up)
                instr.kind = "label"
                instr.label = f"__nop_removed__"
                instr.src1 = None
                # Actually, better to just mark for removal
                instr.kind = "const_load"
                instr.dst = "__dead_branch__"
                instr.src1 = "0"
                instr.label = None

    elif instr.kind == "iffalse_goto":
        v1 = _resolve_const(instr.src1, state)
        if v1 is not None:
            if not v1:
                instr.kind = "goto"
                instr.src1 = None
            else:
                instr.kind = "const_load"
                instr.dst = "__dead_branch__"
                instr.src1 = "0"
                instr.label = None

    elif instr.kind == "print":
        v1 = _resolve_const(instr.src1, state)
        if v1 is not None:
            instr.src1 = str(v1)

    elif instr.kind == "return_val":
        v1 = _resolve_const(instr.src1, state)
        if v1 is not None:
            instr.src1 = str(v1)

    return instr


# ==================== Unreachable Code Elimination ====================

def run_unreachable_elimination(func: Function) -> Function:
    """Remove unreachable basic blocks."""
    func = func.clone()
    body = func.body
    params = [i for i in body if i.kind == "param"]
    func_start = next((i for i in body if i.kind == "func_start"), None)
    func_end = next((i for i in body if i.kind == "func_end"), None)

    cfg = build_cfg([i for i in body if i.kind != "param"])
    reachable = cfg.reachable_block_ids()

    # Remove unreachable blocks
    for bid in list(cfg.blocks.keys()):
        if bid not in reachable:
            del cfg.blocks[bid]

    new_body = cfg_to_instructions(cfg, func_start, func_end, params)

    # Also remove __dead_branch__ assignments
    new_body = [i for i in new_body if not (i.kind == "const_load" and i.dst == "__dead_branch__")]

    func.body = new_body
    return func


# ==================== Common Subexpression Elimination ====================

def run_cse(func: Function) -> Function:
    """Available expressions analysis + CSE."""
    func = func.clone()
    body = [i for i in func.body if i.kind not in ("func_start", "func_end")]
    params_instr = [i for i in func.body if i.kind == "param"]
    func_start = next((i for i in func.body if i.kind == "func_start"), None)
    func_end = next((i for i in func.body if i.kind == "func_end"), None)

    cfg = build_cfg([i for i in func.body if i.kind != "param"])
    reachable = cfg.reachable_block_ids()
    block_ids = sorted(bid for bid in cfg.blocks.keys() if bid in reachable)

    # Available expressions: forward, must (intersection)
    # Expression = (src1, op, src2) -> dst variable that holds it

    # For each block, compute gen and kill sets
    # An expression (src1, op, src2) is generated when we compute it
    # An expression is killed when src1 or src2 or dst is redefined

    # Collect all expressions
    all_exprs: Set[Tuple[str, str, str]] = set()
    for bid in block_ids:
        for instr in cfg.blocks[bid].instructions:
            if instr.kind == "assign_binop":
                all_exprs.add((instr.src1, instr.op, instr.src2))

    if not all_exprs:
        return func

    # Forward available expressions analysis using intersection (must)
    # avail_in[bid] = set of (src1, op, src2, dst_var) that are available at entry
    avail_in: Dict[int, Dict[Tuple[str, str, str], str]] = {}
    avail_out: Dict[int, Dict[Tuple[str, str, str], str]] = {}

    for bid in block_ids:
        avail_in[bid] = {}
        avail_out[bid] = {}

    # Initialize entry to empty, others to "all" (for intersection)
    first_pass = True
    changed = True
    max_iter = 100
    iteration = 0

    while changed and iteration < max_iter:
        changed = False
        iteration += 1
        for bid in block_ids:
            block = cfg.blocks[bid]

            # Compute avail_in from predecessors (intersection)
            preds_in_reachable = [p for p in block.predecessors if p in reachable]
            if not preds_in_reachable or bid == cfg.entry_id:
                new_in = {}
            else:
                # Intersection of all predecessor outputs
                pred_outs = [avail_out[p] for p in preds_in_reachable if p in avail_out]
                if not pred_outs:
                    new_in = {}
                else:
                    new_in = dict(pred_outs[0])
                    for po in pred_outs[1:]:
                        keys_to_remove = []
                        for expr in new_in:
                            if expr not in po:
                                keys_to_remove.append(expr)
                        for k in keys_to_remove:
                            del new_in[k]

            if new_in != avail_in[bid]:
                avail_in[bid] = new_in
                changed = True

            # Transfer function: process block instructions
            avail = dict(avail_in[bid])
            for instr in block.instructions:
                # Kill expressions that reference redefined variables
                defs = instr.defs()
                if defs:
                    for d in defs:
                        to_remove = [e for e in avail if e[0] == d or e[2] == d]
                        for e in to_remove:
                            del avail[e]
                        # Also kill expressions whose result var is this dst
                        to_remove2 = [e for e, v in avail.items() if v == d]
                        for e in to_remove2:
                            del avail[e]

                # Gen: if this is a binop, add to available
                if instr.kind == "assign_binop":
                    expr = (instr.src1, instr.op, instr.src2)
                    avail[expr] = instr.dst

            if avail != avail_out[bid]:
                avail_out[bid] = avail
                changed = True

    # Rewrite: replace redundant computations with copies
    for bid in block_ids:
        block = cfg.blocks[bid]
        avail = dict(avail_in[bid])
        new_instrs = []
        for instr in block.instructions:
            if instr.kind == "assign_binop":
                expr = (instr.src1, instr.op, instr.src2)
                if expr in avail:
                    # Replace with copy from the variable that holds the result
                    new_instr = instr.clone()
                    new_instr.kind = "copy"
                    new_instr.src1 = avail[expr]
                    new_instr.op = None
                    new_instr.src2 = None
                    new_instrs.append(new_instr)
                    # Update avail: this dst now also holds expr
                    avail[expr] = instr.dst
                else:
                    new_instrs.append(instr)
                    avail[expr] = instr.dst
            else:
                new_instrs.append(instr)

            # Kill on defs
            defs = instr.defs()
            if defs and instr.kind != "assign_binop":
                for d in defs:
                    to_remove = [e for e in avail if e[0] == d or e[2] == d]
                    for e in to_remove:
                        del avail[e]
                    to_remove2 = [e for e, v in avail.items() if v == d]
                    for e in to_remove2:
                        del avail[e]

        block.instructions = new_instrs

    new_body = cfg_to_instructions(cfg, func_start, func_end, params_instr)
    func.body = new_body
    return func


# ==================== Dead Code Elimination ====================

def run_dce(func: Function) -> Function:
    """Backward liveness analysis + dead code elimination."""
    func = func.clone()
    params_instr = [i for i in func.body if i.kind == "param"]
    func_start = next((i for i in func.body if i.kind == "func_start"), None)
    func_end = next((i for i in func.body if i.kind == "func_end"), None)

    cfg = build_cfg([i for i in func.body if i.kind != "param"])
    reachable = cfg.reachable_block_ids()
    block_ids = sorted(bid for bid in cfg.blocks.keys() if bid in reachable)

    # Backward liveness analysis
    live_in: Dict[int, Set[str]] = {bid: set() for bid in block_ids}
    live_out: Dict[int, Set[str]] = {bid: set() for bid in block_ids}

    changed = True
    max_iter = 100
    iteration = 0
    while changed and iteration < max_iter:
        changed = False
        iteration += 1
        for bid in reversed(block_ids):
            block = cfg.blocks[bid]

            # live_out = union of live_in of all successors
            new_out: Set[str] = set()
            for s in block.successors:
                if s in live_in:
                    new_out |= live_in[s]

            if new_out != live_out[bid]:
                live_out[bid] = new_out
                changed = True

            # Transfer: walk instructions backward
            live = set(live_out[bid])
            for instr in reversed(block.instructions):
                # Remove defs
                for d in instr.defs():
                    live.discard(d)
                # Add uses
                for u in instr.uses():
                    live.add(u)

            if live != live_in[bid]:
                live_in[bid] = live
                changed = True

    # Eliminate dead assignments
    for bid in block_ids:
        block = cfg.blocks[bid]
        live = set(live_out[bid])
        new_instrs = []

        # Walk backward to determine what's dead
        keep = [True] * len(block.instructions)
        for idx in range(len(block.instructions) - 1, -1, -1):
            instr = block.instructions[idx]
            if instr.defs() and not instr.is_side_effecting():
                dst = instr.defs()[0]
                if dst not in live:
                    keep[idx] = False
                else:
                    live.discard(dst)
                    for u in instr.uses():
                        live.add(u)
            else:
                for u in instr.uses():
                    live.add(u)

        block.instructions = [block.instructions[i] for i in range(len(block.instructions)) if keep[i]]

    new_body = cfg_to_instructions(cfg, func_start, func_end, params_instr)
    func.body = new_body
    return func

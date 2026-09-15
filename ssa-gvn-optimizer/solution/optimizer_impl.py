"""
optimizer_impl.py - Full implementation of GVN + load-store forwarding.

"""
from typing import Dict, List, Optional
from ir import Function, PURE_OPS, COMMUTATIVE_OPS, SIDE_EFFECT_OPS


def compute_rpo(func: Function) -> List[str]:
    """Reverse post-order via iterative DFS."""
    visited: set = set()
    post_order: List[str] = []
    stack = [(func.entry, False)]
    while stack:
        node, processed = stack.pop()
        if processed:
            post_order.append(node)
            continue
        if node in visited:
            continue
        visited.add(node)
        stack.append((node, True))
        for succ in reversed(func.blocks[node].successors()):
            if succ not in visited:
                stack.append((succ, False))
    return list(reversed(post_order))


def compute_dominators(func: Function, rpo: List[str]) -> Dict[str, Optional[str]]:
    """Cooper-Harvey-Kennedy iterative dominator algorithm."""
    rpo_num = {b: i for i, b in enumerate(rpo)}
    doms: Dict[str, Optional[str]] = {b: None for b in rpo}
    doms[func.entry] = func.entry

    def intersect(b1: str, b2: str) -> str:
        while b1 != b2:
            while rpo_num[b1] > rpo_num[b2]:
                b1 = doms[b1]
            while rpo_num[b2] > rpo_num[b1]:
                b2 = doms[b2]
        return b1

    changed = True
    while changed:
        changed = False
        for b in rpo:
            if b == func.entry:
                continue
            preds = func.predecessors(b)
            new_idom: Optional[str] = None
            for p in preds:
                if doms[p] is not None:
                    if new_idom is None:
                        new_idom = p
                    else:
                        new_idom = intersect(new_idom, p)
            if new_idom is not None and doms[b] != new_idom:
                doms[b] = new_idom
                changed = True

    doms[func.entry] = None
    return doms


def optimize(func: Function) -> Function:
    """Combined GVN + load-store forwarding + trivial phi elimination."""
    rpo = compute_rpo(func)
    doms = compute_dominators(func, rpo)

    # Canonical mapping: value name -> representative name
    canonical: Dict[str, str] = {f"a{i}": f"a{i}" for i in range(func.n_args)}

    # Per-block saved state for dominator children
    block_vmaps: Dict[str, dict] = {}
    block_hcaches: Dict[str, dict] = {}

    def resolve(val):
        if isinstance(val, int):
            return val
        return canonical.get(val, val)

    def value_key(op: str, resolved_args: list) -> tuple:
        if op in COMMUTATIVE_OPS and len(resolved_args) == 2:
            return (op, tuple(sorted(str(a) for a in resolved_args)))
        return (op, tuple(str(a) for a in resolved_args))

    for bname in rpo:
        block = func.blocks[bname]
        idom = doms.get(bname)

        # Inherit from immediate dominator
        if idom is not None and idom in block_vmaps:
            vmap = dict(block_vmaps[idom])
            hcache = dict(block_hcaches[idom])
        else:
            vmap: dict = {}
            hcache: dict = {}

        # ---- Trivial phi elimination ----
        new_phis = []
        for phi in block.phis:
            resolved_inc = {pred: resolve(val) for pred, val in phi.incoming.items()}
            unique = set(v for v in resolved_inc.values() if v != phi.dst)
            if len(unique) == 1:
                canonical[phi.dst] = unique.pop()
            elif len(unique) == 0:
                canonical[phi.dst] = phi.dst
            else:
                phi.incoming = resolved_inc
                canonical[phi.dst] = phi.dst
                new_phis.append(phi)
        block.phis = new_phis

        # ---- Instructions ----
        new_instrs = []
        for instr in block.instrs:
            op = instr.op

            if op == "const":
                key = ("const", (instr.args[0],))
                if key in vmap:
                    canonical[instr.dst] = vmap[key]
                    continue
                vmap[key] = instr.dst
                canonical[instr.dst] = instr.dst
                new_instrs.append(instr)

            elif op in PURE_OPS:
                resolved = [resolve(a) for a in instr.args]
                key = value_key(op, resolved)
                if key in vmap:
                    canonical[instr.dst] = vmap[key]
                    continue
                vmap[key] = instr.dst
                canonical[instr.dst] = instr.dst
                instr.args = resolved
                new_instrs.append(instr)

            elif op == "load":
                obj = resolve(instr.args[0])
                offset = instr.args[1]
                heap_key = (obj, offset)
                if heap_key in hcache:
                    canonical[instr.dst] = hcache[heap_key]
                    continue
                hcache[heap_key] = instr.dst
                canonical[instr.dst] = instr.dst
                instr.args = [obj, offset]
                new_instrs.append(instr)

            elif op == "store":
                obj = resolve(instr.args[0])
                offset = instr.args[1]
                val = resolve(instr.args[2])
                heap_key = (obj, offset)
                # Redundant store check
                if heap_key in hcache and hcache[heap_key] == val:
                    continue
                # Invalidate alias class (same offset, any object)
                hcache = {k: v for k, v in hcache.items() if k[1] != offset}
                hcache[heap_key] = val
                canonical[instr.dst] = instr.dst
                instr.args = [obj, offset, val]
                new_instrs.append(instr)

            elif op in SIDE_EFFECT_OPS:
                resolved = [resolve(a) for a in instr.args]
                canonical[instr.dst] = instr.dst
                hcache = {}
                instr.args = resolved
                new_instrs.append(instr)

            else:
                resolved = [resolve(a) for a in instr.args]
                canonical[instr.dst] = instr.dst
                instr.args = resolved
                new_instrs.append(instr)

        block.instrs = new_instrs

        # ---- Terminator ----
        if block.term:
            block.term.args = [resolve(a) for a in block.term.args]

        # Save state for dominated children
        block_vmaps[bname] = vmap
        block_hcaches[bname] = hcache

    return func

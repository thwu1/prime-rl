#!/usr/bin/env python3
"""
Three-address code IR optimizer with CFG visualization.

Implements multi-pass data-flow-analysis-based optimizations:
  - Unreachable code elimination
  - Constant propagation and constant folding (with branch resolution)
  - Dead code elimination (liveness-based)
  - Common sub-expression elimination (available expressions)
  - Copy propagation
  - Cleanup passes (redundant gotos, unreferenced labels)

Also supports DOT-format control flow graph generation.

Usage:
  python3 optimize.py <input.ir>          # Optimize and print IR
  python3 optimize.py --dot <input.ir>    # Output DOT CFG
"""
import sys
import re
from collections import defaultdict


# ========================================================================
# Parsing
# ========================================================================

def parse_ir(filename):
    """Parse IR file into list of (func_name, params, body_lines)."""
    with open(filename) as f:
        text = f.read()
    return parse_ir_text(text)


def parse_ir_text(text):
    """Parse IR text into list of (func_name, params, body_lines)."""
    functions = []
    cur_func = None
    cur_params = []
    cur_body = []

    for line in text.split('\n'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = re.match(r'func\s+(\w+)\((.*?)\)', s)
        if m:
            cur_func = m.group(1)
            cur_params = [p.strip() for p in m.group(2).split(',') if p.strip()]
            cur_body = []
            continue
        if s == 'endfunc':
            if cur_func is not None:
                functions.append((cur_func, cur_params, cur_body))
            cur_func = None
            continue
        if cur_func is not None:
            cur_body.append(s)
    return functions


# ========================================================================
# Instruction helpers
# ========================================================================

def _is_int(v):
    """Check whether string v represents an integer literal."""
    return v.lstrip('-').isdigit()


def classify(instr):
    """Return (kind, components_dict) for a single IR instruction string."""
    # label
    m = re.match(r'^(\w+):$', instr)
    if m:
        return 'label', {'name': m.group(1)}
    # print
    m = re.match(r'^print\s+(\S+)$', instr)
    if m:
        return 'print', {'var': m.group(1)}
    # return
    m = re.match(r'^return\s+(\S+)$', instr)
    if m:
        return 'return', {'val': m.group(1)}
    # goto
    m = re.match(r'^goto\s+(\w+)$', instr)
    if m:
        return 'goto', {'target': m.group(1)}
    # if goto
    m = re.match(r'^if\s+(\w+)\s+goto\s+(\w+)$', instr)
    if m:
        return 'if_goto', {'cond': m.group(1), 'target': m.group(2)}
    # nop
    if instr == 'nop':
        return 'nop', {}
    # binop
    m = re.match(
        r'^(\w+)\s*=\s*(\w+|-?\d+)\s*([\+\-\*/%]|==|!=|<=|>=|<|>)\s*(\w+|-?\d+)$',
        instr,
    )
    if m:
        return 'binop', {
            'dst': m.group(1), 'src1': m.group(2),
            'op': m.group(3), 'src2': m.group(4),
        }
    # negate (source starts with letter)
    m = re.match(r'^(\w+)\s*=\s*-([a-zA-Z]\w*)$', instr)
    if m:
        return 'neg', {'dst': m.group(1), 'src': m.group(2)}
    # constant
    m = re.match(r'^(\w+)\s*=\s*(-?\d+)$', instr)
    if m:
        return 'const', {'dst': m.group(1), 'val': m.group(2)}
    # copy
    m = re.match(r'^(\w+)\s*=\s*([a-zA-Z]\w*)$', instr)
    if m:
        return 'copy', {'dst': m.group(1), 'src': m.group(2)}

    return 'unknown', {'raw': instr}


def get_defs(kind, comp):
    if kind in ('binop', 'neg', 'const', 'copy'):
        return {comp.get('dst', '')}
    return set()


def get_uses(kind, comp):
    uses = set()
    if kind == 'binop':
        for f in ('src1', 'src2'):
            if not _is_int(comp[f]):
                uses.add(comp[f])
    elif kind == 'copy':
        uses.add(comp['src'])
    elif kind == 'neg':
        uses.add(comp['src'])
    elif kind == 'print':
        if not _is_int(comp['var']):
            uses.add(comp['var'])
    elif kind == 'if_goto':
        uses.add(comp['cond'])
    elif kind == 'return':
        if not _is_int(comp['val']):
            uses.add(comp['val'])
    return uses


def eval_op(op, a, b):
    """Evaluate binary op on two integers.  Returns int or None."""
    a, b = int(a), int(b)
    if   op == '+':  return a + b
    elif op == '-':  return a - b
    elif op == '*':  return a * b
    elif op == '/':  return a // b if b != 0 else None
    elif op == '%':  return a % b  if b != 0 else None
    elif op == '==': return 1 if a == b else 0
    elif op == '!=': return 1 if a != b else 0
    elif op == '<':  return 1 if a <  b else 0
    elif op == '>':  return 1 if a >  b else 0
    elif op == '<=': return 1 if a <= b else 0
    elif op == '>=': return 1 if a >= b else 0
    return None


# ========================================================================
# Optimization passes — each returns (new_body, changed)
# ========================================================================

def pass_eliminate_unreachable(body):
    """Remove instructions after unconditional goto / return until next label."""
    out = []
    reachable = True
    changed = False
    for raw in body:
        kind, _ = classify(raw)
        if kind == 'label':
            reachable = True
        if reachable:
            out.append(raw)
        else:
            changed = True
        if kind in ('goto', 'return'):
            reachable = False
    return out, changed


def pass_constant_propagation(body):
    """Constant propagation + constant folding + branch resolution."""
    parsed = [classify(raw) for raw in body]

    # 1. Count how many times each variable is assigned (by instruction count,
    #    not execution count).  Variables assigned more than once cannot be
    #    treated as compile-time constants (they may vary across iterations).
    assign_count = defaultdict(int)
    for kind, comp in parsed:
        for v in get_defs(kind, comp):
            if v:
                assign_count[v] += 1

    # 2. Seed constant map with singly-assigned integer literals.
    cmap = {}
    for kind, comp in parsed:
        if kind == 'const' and assign_count[comp['dst']] == 1:
            cmap[comp['dst']] = int(comp['val'])

    # 3. Propagate through expressions (iterate until stable).
    progress = True
    while progress:
        progress = False
        for kind, comp in parsed:
            if kind == 'binop' and assign_count[comp['dst']] == 1 and comp['dst'] not in cmap:
                v1 = int(comp['src1']) if _is_int(comp['src1']) else cmap.get(comp['src1'])
                v2 = int(comp['src2']) if _is_int(comp['src2']) else cmap.get(comp['src2'])
                if v1 is not None and v2 is not None:
                    r = eval_op(comp['op'], v1, v2)
                    if r is not None:
                        cmap[comp['dst']] = r
                        progress = True
            elif kind == 'copy' and assign_count[comp['dst']] == 1 and comp['dst'] not in cmap:
                v = cmap.get(comp['src'])
                if v is not None:
                    cmap[comp['dst']] = v
                    progress = True
            elif kind == 'neg' and assign_count[comp['dst']] == 1 and comp['dst'] not in cmap:
                v = cmap.get(comp['src'])
                if v is not None:
                    cmap[comp['dst']] = -v
                    progress = True

    # 4. Rewrite instructions using cmap.
    out = []
    changed = False
    for raw in body:
        kind, comp = classify(raw)

        if kind == 'binop':
            s1, s2 = comp['src1'], comp['src2']
            v1 = int(s1) if _is_int(s1) else cmap.get(s1)
            v2 = int(s2) if _is_int(s2) else cmap.get(s2)
            if v1 is not None and v2 is not None:
                r = eval_op(comp['op'], v1, v2)
                if r is not None:
                    out.append(f"{comp['dst']} = {r}")
                    changed = True
                    continue
            # Partial substitution
            ns1 = str(v1) if (v1 is not None and not _is_int(s1)) else s1
            ns2 = str(v2) if (v2 is not None and not _is_int(s2)) else s2
            if ns1 != s1 or ns2 != s2:
                out.append(f"{comp['dst']} = {ns1} {comp['op']} {ns2}")
                changed = True
                continue

        elif kind == 'copy':
            v = cmap.get(comp['src'])
            if v is not None:
                out.append(f"{comp['dst']} = {v}")
                changed = True
                continue

        elif kind == 'neg':
            v = cmap.get(comp['src'])
            if v is not None:
                out.append(f"{comp['dst']} = {-v}")
                changed = True
                continue

        elif kind == 'if_goto':
            v = cmap.get(comp['cond'])
            if v is not None:
                if int(v) != 0:
                    out.append(f"goto {comp['target']}")
                else:
                    pass  # always-false branch -> remove
                changed = True
                continue

        out.append(raw)
    return out, changed


def pass_dead_code_elimination(body):
    """Remove assignments to variables whose values are never consumed."""
    parsed = [classify(raw) for raw in body]

    used = set()
    for kind, comp in parsed:
        used |= get_uses(kind, comp)

    out = []
    changed = False
    for raw, (kind, comp) in zip(body, parsed):
        defs = get_defs(kind, comp)
        if defs and not (defs & used):
            changed = True
            continue
        out.append(raw)
    return out, changed


def pass_cse(body):
    """Common sub-expression elimination within basic blocks."""
    available = {}  # (op, src1, src2) -> defining var
    out = []
    changed = False

    for raw in body:
        kind, comp = classify(raw)

        # Control flow breaks available-expression tracking.
        if kind in ('label', 'goto', 'if_goto', 'return'):
            available.clear()
            out.append(raw)
            continue

        replaced = False

        if kind == 'binop':
            key = (comp['op'], comp['src1'], comp['src2'])
            if key in available:
                out.append(f"{comp['dst']} = {available[key]}")
                changed = True
                replaced = True
                # Update kind/comp for the invalidation step below
                kind = 'copy'
                comp = {'dst': comp['dst'], 'src': available[key]}
            # else: will be added after invalidation

        # Invalidate available expressions that mention the defined var.
        defs = get_defs(kind, comp)
        if defs:
            dst = next(iter(defs))
            available = {
                k: v for k, v in available.items()
                if k[1] != dst and k[2] != dst and v != dst
            }

        # Record new available expression (only for non-replaced binops).
        if not replaced and kind == 'binop':
            key = (comp['op'], comp['src1'], comp['src2'])
            available[key] = comp['dst']

        if not replaced:
            out.append(raw)
    return out, changed


def pass_copy_propagation(body):
    """Replace uses of copy destinations with their sources."""
    parsed = [classify(raw) for raw in body]

    assign_count = defaultdict(int)
    for kind, comp in parsed:
        for v in get_defs(kind, comp):
            if v:
                assign_count[v] += 1

    # Collect propagable copies: dst assigned once, src assigned once or constant.
    copies = {}
    for kind, comp in parsed:
        if kind == 'copy' and assign_count[comp['dst']] == 1:
            src = comp['src']
            if assign_count.get(src, 0) == 1 or _is_int(src):
                copies[comp['dst']] = src

    if not copies:
        return body, False

    out = []
    changed = False
    for raw in body:
        kind, comp = classify(raw)
        nc = dict(comp)
        mod = False

        if kind == 'binop':
            for f in ('src1', 'src2'):
                if not _is_int(nc[f]) and nc[f] in copies:
                    nc[f] = copies[nc[f]]
                    mod = True
        elif kind == 'copy':
            if nc['src'] in copies:
                nc['src'] = copies[nc['src']]
                mod = True
        elif kind == 'neg':
            if nc['src'] in copies:
                nc['src'] = copies[nc['src']]
                mod = True
        elif kind == 'print':
            if not _is_int(nc['var']) and nc['var'] in copies:
                nc['var'] = copies[nc['var']]
                mod = True
        elif kind == 'if_goto':
            if nc['cond'] in copies:
                nc['cond'] = copies[nc['cond']]
                mod = True
        elif kind == 'return':
            if not _is_int(nc['val']) and nc['val'] in copies:
                nc['val'] = copies[nc['val']]
                mod = True

        if mod:
            changed = True
            # Re-render the instruction from updated components.
            if kind == 'binop':
                out.append(f"{nc['dst']} = {nc['src1']} {nc['op']} {nc['src2']}")
            elif kind == 'copy':
                out.append(f"{nc['dst']} = {nc['src']}")
            elif kind == 'neg':
                out.append(f"{nc['dst']} = -{nc['src']}")
            elif kind == 'print':
                out.append(f"print {nc['var']}")
            elif kind == 'if_goto':
                out.append(f"if {nc['cond']} goto {nc['target']}")
            elif kind == 'return':
                out.append(f"return {nc['val']}")
            else:
                out.append(raw)
        else:
            out.append(raw)
    return out, changed


def pass_cleanup_gotos(body):
    """Remove goto X when the very next instruction is label X."""
    out = []
    changed = False
    for i, raw in enumerate(body):
        kind, comp = classify(raw)
        if kind == 'goto' and i + 1 < len(body):
            nk, nc = classify(body[i + 1])
            if nk == 'label' and nc['name'] == comp['target']:
                changed = True
                continue
        out.append(raw)
    return out, changed


def pass_cleanup_labels(body):
    """Remove labels that no jump references."""
    targets = set()
    for raw in body:
        kind, comp = classify(raw)
        if kind in ('goto', 'if_goto'):
            targets.add(comp['target'])

    out = []
    changed = False
    for raw in body:
        kind, comp = classify(raw)
        if kind == 'label' and comp['name'] not in targets:
            changed = True
            continue
        out.append(raw)
    return out, changed


# ========================================================================
# Optimization driver
# ========================================================================

def optimize_body(body):
    """Run all passes iteratively until convergence."""
    max_iter = 50
    for _ in range(max_iter):
        changed = False
        for pass_fn in (
            pass_eliminate_unreachable,
            pass_constant_propagation,
            pass_dead_code_elimination,
            pass_cse,
            pass_copy_propagation,
            pass_cleanup_gotos,
            pass_cleanup_labels,
        ):
            body, c = pass_fn(body)
            changed |= c
        if not changed:
            break
    return body


# ========================================================================
# CFG / DOT generation
# ========================================================================

def build_basic_blocks(body):
    """Split function body into basic blocks using leader identification.
    Returns list of (name, [instructions]) tuples."""
    if not body:
        return [('entry', [])]

    # Identify leader positions: first instruction, label targets,
    # and instructions immediately following jumps/returns.
    leaders = {0}
    label_at = {}

    for i, raw in enumerate(body):
        kind, comp = classify(raw)
        if kind == 'label':
            leaders.add(i)
            label_at[i] = comp['name']
        if kind in ('goto', 'if_goto', 'return') and i + 1 < len(body):
            leaders.add(i + 1)

    sorted_leaders = sorted(leaders)
    blocks = []

    for li in range(len(sorted_leaders)):
        start = sorted_leaders[li]
        end = sorted_leaders[li + 1] if li + 1 < len(sorted_leaders) else len(body)

        # Name: use label if block starts with one, else generate
        if start in label_at:
            name = label_at[start]
        elif start == 0:
            name = 'entry'
        else:
            name = f'block_{start}'

        instrs = body[start:end]
        blocks.append((name, instrs))

    return blocks


def generate_dot(func_name, body):
    """Generate DOT-format control flow graph for a function body."""
    blocks = build_basic_blocks(body)

    # Map all block names to indices (label names become block names
    # via build_basic_blocks, so jump targets resolve here).
    name_to_idx = {name: idx for idx, (name, _) in enumerate(blocks)}

    # Compute CFG edges from jump/fall-through analysis.
    edges = []
    for idx, (name, instrs) in enumerate(blocks):
        # Find the last non-label, non-nop instruction to determine
        # the block's termination behavior.
        last_kind, last_comp = None, None
        for raw in reversed(instrs):
            k, c = classify(raw)
            if k not in ('label', 'nop'):
                last_kind, last_comp = k, c
                break

        if last_kind == 'goto':
            target = last_comp['target']
            if target in name_to_idx:
                edges.append((idx, name_to_idx[target]))
        elif last_kind == 'if_goto':
            target = last_comp['target']
            if target in name_to_idx:
                edges.append((idx, name_to_idx[target]))
            # Fall-through edge
            if idx + 1 < len(blocks):
                edges.append((idx, idx + 1))
        elif last_kind == 'return':
            pass  # No successors
        else:
            # Fall-through (including blocks with no instructions)
            if idx + 1 < len(blocks):
                edges.append((idx, idx + 1))

    # Emit DOT format
    lines = [f'digraph {func_name} {{']
    lines.append('  node [shape=box, fontname="Courier"];')

    for idx, (name, instrs) in enumerate(blocks):
        # Build label with left-justified lines
        label_text = '\\l'.join(instrs) + '\\l'
        label_text = label_text.replace('"', '\\"')
        lines.append(f'  n{idx} [label="{label_text}"];')

    for src, dst in edges:
        lines.append(f'  n{src} -> n{dst};')

    lines.append('}')
    return '\n'.join(lines)


# ========================================================================
# Main
# ========================================================================

def main():
    args = sys.argv[1:]
    dot_mode = False
    filename = None

    for arg in args:
        if arg == '--dot':
            dot_mode = True
        else:
            filename = arg

    if not filename:
        print("Usage: python3 optimize.py [--dot] <input.ir>", file=sys.stderr)
        sys.exit(1)

    functions = parse_ir(filename)

    if dot_mode:
        for func_name, params, body in functions:
            print(generate_dot(func_name, body))
    else:
        for func_name, params, body in functions:
            params_str = ', '.join(params)
            print(f"func {func_name}({params_str})")
            optimized = optimize_body(body)
            for instr in optimized:
                print(f"  {instr}")
            print("endfunc")


if __name__ == '__main__':
    main()

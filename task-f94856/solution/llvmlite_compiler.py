#!/usr/bin/env python3
"""LLVMlite IR to x86-64 compiler backend.

Reads a subset of LLVM IR (.ll files) and generates AT&T syntax
x86-64 assembly (.s files) compatible with the System V AMD64 ABI.

"""
import sys
import re


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.ll output.s", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    prog = parse_program(source)
    asm = compile_program(prog)
    with open(sys.argv[2], "w") as f:
        f.write(asm)


# ==================== PARSING ====================


def parse_operand(s):
    """Parse an operand string into (kind, value)."""
    s = s.strip()
    if s.startswith("@"):
        return ("global", s[1:])
    if s.startswith("%"):
        return ("reg", s[1:])
    try:
        return ("const", int(s))
    except ValueError:
        return ("unknown", s)


def parse_call_args(args_str):
    """Parse function call argument list."""
    args_str = args_str.strip()
    if not args_str:
        return []
    # Split on commas respecting parenthesis depth
    parts, depth, cur = [], 0, ""
    for ch in args_str:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    args = []
    for part in parts:
        tokens = part.rsplit(None, 1)
        if len(tokens) == 2:
            args.append((tokens[0].strip(), parse_operand(tokens[1])))
    return args


def parse_instruction(line):
    """Parse a single IR instruction line into a dict."""
    line = line.strip()
    # Strip end-of-line comments
    if ";" in line:
        line = line[: line.index(";")].strip()
    if not line:
        return None

    # --- Terminators ---

    if line == "ret void":
        return {"type": "ret", "ret_ty": "void", "val": None}

    m = re.match(r"ret\s+(\S+)\s+(.+)", line)
    if m:
        return {"type": "ret", "ret_ty": m.group(1), "val": parse_operand(m.group(2))}

    m = re.match(
        r"br\s+i1\s+(.+?),\s*label\s+%(\w+),\s*label\s+%(\w+)", line
    )
    if m:
        return {
            "type": "br_cond",
            "cond": parse_operand(m.group(1)),
            "true_label": m.group(2),
            "false_label": m.group(3),
        }

    m = re.match(r"br\s+label\s+%(\w+)", line)
    if m:
        return {"type": "br_uncond", "target": m.group(1)}

    # --- Phi ---

    m = re.match(r"(%\S+)\s*=\s*phi\s+(\S+)\s+(.*)", line)
    if m:
        dest = m.group(1)[1:]
        incoming = []
        for pair in re.finditer(r"\[\s*(.+?)\s*,\s*%(\w+)\s*\]", m.group(3)):
            incoming.append((parse_operand(pair.group(1)), pair.group(2)))
        return {"type": "phi", "dest": dest, "ty": m.group(2), "incoming": incoming}

    # --- Binary ops ---

    m = re.match(
        r"(%\S+)\s*=\s*(add|sub|mul|and|or|xor|shl|lshr|ashr)\s+(\S+)\s+(.+?),\s*(.+)",
        line,
    )
    if m:
        return {
            "type": "binop",
            "dest": m.group(1)[1:],
            "op": m.group(2),
            "ty": m.group(3),
            "left": parse_operand(m.group(4)),
            "right": parse_operand(m.group(5)),
        }

    # --- Comparison ---

    m = re.match(
        r"(%\S+)\s*=\s*icmp\s+(\w+)\s+(\S+)\s+(.+?),\s*(.+)", line
    )
    if m:
        return {
            "type": "icmp",
            "dest": m.group(1)[1:],
            "cond": m.group(2),
            "ty": m.group(3),
            "left": parse_operand(m.group(4)),
            "right": parse_operand(m.group(5)),
        }

    # --- Alloca ---

    m = re.match(r"(%\S+)\s*=\s*alloca\s+(.+)", line)
    if m:
        return {"type": "alloca", "dest": m.group(1)[1:], "alloc_ty": m.group(2).strip()}

    # --- Load ---

    m = re.match(r"(%\S+)\s*=\s*load\s+(\S+),\s*\S+\s+(.+)", line)
    if m:
        return {
            "type": "load",
            "dest": m.group(1)[1:],
            "ty": m.group(2),
            "ptr": parse_operand(m.group(3)),
        }

    # --- Store ---

    m = re.match(r"store\s+(\S+)\s+(.+?),\s*\S+\s+(.+)", line)
    if m:
        return {
            "type": "store",
            "val": parse_operand(m.group(2)),
            "ptr": parse_operand(m.group(3)),
        }

    # --- GEP ---

    m = re.match(
        r"(%\S+)\s*=\s*getelementptr\s+(\S+),\s*\S+\s+(.+?),\s*\S+\s+(.+)",
        line,
    )
    if m:
        return {
            "type": "gep",
            "dest": m.group(1)[1:],
            "base_ty": m.group(2),
            "ptr": parse_operand(m.group(3)),
            "idx": parse_operand(m.group(4)),
        }

    # --- Call with return value ---

    m = re.match(r"(%\S+)\s*=\s*call\s+(\S+)\s+@(\w+)\(([^)]*)\)", line)
    if m:
        return {
            "type": "call",
            "dest": m.group(1)[1:],
            "ret_ty": m.group(2),
            "func": m.group(3),
            "args": parse_call_args(m.group(4)),
        }

    # --- Void call ---

    m = re.match(r"call\s+void\s+@(\w+)\(([^)]*)\)", line)
    if m:
        return {
            "type": "call",
            "dest": None,
            "ret_ty": "void",
            "func": m.group(1),
            "args": parse_call_args(m.group(2)),
        }

    # --- Zext ---

    m = re.match(r"(%\S+)\s*=\s*zext\s+(\S+)\s+(.+?)\s+to\s+(\S+)", line)
    if m:
        return {
            "type": "zext",
            "dest": m.group(1)[1:],
            "from_ty": m.group(2),
            "val": parse_operand(m.group(3)),
            "to_ty": m.group(4),
        }

    return None


def parse_function(lines):
    """Parse a function definition from its source lines."""
    header = lines[0].strip()
    m = re.match(r"define\s+(\S+)\s+@(\w+)\(([^)]*)\)\s*\{?", header)
    if not m:
        raise ValueError(f"Bad function header: {header}")
    name = m.group(2)
    ret_ty = m.group(1)

    params = []
    if m.group(3).strip():
        for p in m.group(3).split(","):
            p = p.strip()
            tokens = p.rsplit(None, 1)
            if len(tokens) == 2:
                params.append((tokens[0], tokens[1].lstrip("%")))

    blocks = []
    label = None
    phis, instrs, term = [], [], None
    started = False

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if ";" in line:
            line = line[: line.index(";")].strip()
        if not line or line == "}":
            continue

        lm = re.match(r"^(\w+)\s*:\s*$", line)
        if lm:
            if started and term is not None:
                blocks.append(
                    {"label": label, "phis": phis, "instrs": instrs, "term": term}
                )
            label = lm.group(1)
            phis, instrs, term = [], [], None
            started = True
            continue

        if not started:
            label = "_entry"
            started = True

        instr = parse_instruction(line)
        if instr is None:
            continue
        if instr["type"] in ("ret", "br_cond", "br_uncond"):
            term = instr
        elif instr["type"] == "phi":
            phis.append(instr)
        else:
            instrs.append(instr)

    if started and term is not None:
        blocks.append({"label": label, "phis": phis, "instrs": instrs, "term": term})

    return {"name": name, "ret_ty": ret_ty, "params": params, "blocks": blocks}


def parse_program(source):
    """Parse the entire .ll source into a program structure."""
    lines = source.split("\n")
    globs, decls, funcs = [], [], []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith(";"):
            i += 1
            continue

        gm = re.match(r"@(\w+)\s*=\s*global\s+(\S+)\s+(-?\d+)", line)
        if gm:
            globs.append(
                {"name": gm.group(1), "ty": gm.group(2), "init": int(gm.group(3))}
            )
            i += 1
            continue

        dm = re.match(r"declare\s+(\S+)\s+@(\w+)\(([^)]*)\)", line)
        if dm:
            decls.append({"name": dm.group(2), "ret_ty": dm.group(1)})
            i += 1
            continue

        if line.startswith("define"):
            func_lines = [line]
            i += 1
            depth = line.count("{") - line.count("}")
            while i < len(lines) and depth > 0:
                func_lines.append(lines[i])
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            funcs.append(parse_function(func_lines))
            continue

        i += 1

    return {"globals": globs, "declarations": decls, "functions": funcs}


# ==================== CODE GENERATION ====================

ARG_REGS = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]

ICMP_TO_SET = {
    "eq": "sete",
    "ne": "setne",
    "slt": "setl",
    "sle": "setle",
    "sgt": "setg",
    "sge": "setge",
    "ult": "setb",
    "ule": "setbe",
}

BINOP_TO_X86 = {
    "add": "addq",
    "sub": "subq",
    "and": "andq",
    "or": "orq",
    "xor": "xorq",
}


def type_size(ty):
    """Return the byte size of an IR type (for GEP offset computation)."""
    if ty == "i8":
        return 1
    return 8  # i64, i1 (stored as 8 bytes), pointers


def emit_load(op, reg, slots):
    """Emit instructions to load an operand value into a register."""
    kind, val = op
    if kind == "const":
        return [f"    movq ${val}, {reg}"]
    if kind == "reg":
        return [f"    movq {slots[val]}(%rbp), {reg}"]
    if kind == "global":
        return [f"    leaq {val}(%rip), {reg}"]
    return []


def compile_instr(instr, slots, alloca_data, fname):
    """Compile a single non-terminator instruction to x86-64."""
    asm = []
    t = instr["type"]

    if t == "binop":
        dest, op = instr["dest"], instr["op"]
        asm.extend(emit_load(instr["left"], "%rax", slots))
        asm.extend(emit_load(instr["right"], "%rcx", slots))
        if op in BINOP_TO_X86:
            asm.append(f"    {BINOP_TO_X86[op]} %rcx, %rax")
        elif op == "mul":
            asm.append("    imulq %rcx, %rax")
        elif op == "shl":
            asm.append("    shlq %cl, %rax")
        elif op == "lshr":
            asm.append("    shrq %cl, %rax")
        elif op == "ashr":
            asm.append("    sarq %cl, %rax")
        asm.append(f"    movq %rax, {slots[dest]}(%rbp)")

    elif t == "icmp":
        dest = instr["dest"]
        asm.extend(emit_load(instr["left"], "%rax", slots))
        asm.extend(emit_load(instr["right"], "%rcx", slots))
        asm.append("    cmpq %rcx, %rax")
        asm.append(f"    {ICMP_TO_SET[instr['cond']]} %al")
        asm.append("    movzbq %al, %rax")
        asm.append(f"    movq %rax, {slots[dest]}(%rbp)")

    elif t == "alloca":
        dest = instr["dest"]
        asm.append(f"    leaq {alloca_data[dest]}(%rbp), %rax")
        asm.append(f"    movq %rax, {slots[dest]}(%rbp)")

    elif t == "load":
        dest = instr["dest"]
        asm.extend(emit_load(instr["ptr"], "%rax", slots))
        asm.append("    movq (%rax), %rax")
        asm.append(f"    movq %rax, {slots[dest]}(%rbp)")

    elif t == "store":
        asm.extend(emit_load(instr["val"], "%rcx", slots))
        asm.extend(emit_load(instr["ptr"], "%rax", slots))
        asm.append("    movq %rcx, (%rax)")

    elif t == "gep":
        dest = instr["dest"]
        sz = type_size(instr["base_ty"])
        asm.extend(emit_load(instr["ptr"], "%rax", slots))
        asm.extend(emit_load(instr["idx"], "%rcx", slots))
        asm.append(f"    imulq ${sz}, %rcx, %rcx")
        asm.append("    addq %rcx, %rax")
        asm.append(f"    movq %rax, {slots[dest]}(%rbp)")

    elif t == "call":
        # Load arguments into ABI registers
        for i, (_, arg_op) in enumerate(instr["args"]):
            if i < len(ARG_REGS):
                asm.extend(emit_load(arg_op, ARG_REGS[i], slots))
        asm.append(f"    call {instr['func']}")
        if instr["dest"] is not None:
            asm.append(f"    movq %rax, {slots[instr['dest']]}(%rbp)")

    elif t == "zext":
        dest = instr["dest"]
        asm.extend(emit_load(instr["val"], "%rax", slots))
        asm.append(f"    movq %rax, {slots[dest]}(%rbp)")

    return asm


def emit_phi_copies(src_label, dst_label, phi_map, slots):
    """Emit phi-node resolution copies for a control flow edge."""
    asm = []
    copies = phi_map.get((src_label, dst_label), [])
    for dest_var, src_op in copies:
        asm.extend(emit_load(src_op, "%rax", slots))
        asm.append(f"    movq %rax, {slots[dest_var]}(%rbp)")
    return asm


def compile_term(term, cur_label, slots, phi_map, fname):
    """Compile a terminator instruction."""
    asm = []

    if term["type"] == "ret":
        if term["val"] is not None:
            asm.extend(emit_load(term["val"], "%rax", slots))
        asm.append("    movq %rbp, %rsp")
        asm.append("    popq %rbp")
        asm.append("    retq")

    elif term["type"] == "br_uncond":
        tgt = term["target"]
        asm.extend(emit_phi_copies(cur_label, tgt, phi_map, slots))
        asm.append(f"    jmp .L{fname}_{tgt}")

    elif term["type"] == "br_cond":
        tl = term["true_label"]
        fl = term["false_label"]
        asm.extend(emit_load(term["cond"], "%rax", slots))
        asm.append("    testq %rax, %rax")
        asm.append(f"    je .L{fname}_fe_{cur_label}")
        # True edge
        asm.extend(emit_phi_copies(cur_label, tl, phi_map, slots))
        asm.append(f"    jmp .L{fname}_{tl}")
        # False edge
        asm.append(f".L{fname}_fe_{cur_label}:")
        asm.extend(emit_phi_copies(cur_label, fl, phi_map, slots))
        asm.append(f"    jmp .L{fname}_{fl}")

    return asm


def compile_function(func):
    """Compile a function definition to x86-64 assembly lines."""
    asm = []
    name = func["name"]

    # Collect all SSA variables
    all_vars = set()
    alloca_set = set()
    for _, pn in func["params"]:
        all_vars.add(pn)
    for blk in func["blocks"]:
        for phi in blk["phis"]:
            all_vars.add(phi["dest"])
        for ins in blk["instrs"]:
            d = ins.get("dest")
            if d is not None:
                all_vars.add(d)
            if ins["type"] == "alloca":
                alloca_set.add(ins["dest"])

    # Assign stack slots for temporaries
    slots = {}
    off = 0
    for v in sorted(all_vars):
        off += 8
        slots[v] = -off

    # Assign stack slots for alloca data (separate from temporary slots)
    alloca_data = {}
    for v in sorted(alloca_set):
        off += 8
        alloca_data[v] = -off

    # Round frame to 16-byte alignment
    frame = off if off % 16 == 0 else off + (16 - off % 16)

    # Build phi copy map: (pred_label, succ_label) -> [(dest_var, src_operand), ...]
    phi_map = {}
    for blk in func["blocks"]:
        for phi in blk["phis"]:
            for val, pred in phi["incoming"]:
                key = (pred, blk["label"])
                phi_map.setdefault(key, []).append((phi["dest"], val))

    # Prologue
    asm.append(f"    .globl {name}")
    asm.append(f"{name}:")
    asm.append("    pushq %rbp")
    asm.append("    movq %rsp, %rbp")
    if frame > 0:
        asm.append(f"    subq ${frame}, %rsp")

    # Save parameters to their stack slots
    for i, (_, pn) in enumerate(func["params"]):
        if i < len(ARG_REGS):
            asm.append(f"    movq {ARG_REGS[i]}, {slots[pn]}(%rbp)")

    # Emit basic blocks
    for blk in func["blocks"]:
        asm.append(f".L{name}_{blk['label']}:")
        for ins in blk["instrs"]:
            asm.extend(compile_instr(ins, slots, alloca_data, name))
        asm.extend(compile_term(blk["term"], blk["label"], slots, phi_map, name))

    return asm


def compile_program(prog):
    """Compile the entire program to x86-64 assembly text."""
    asm = []

    # Emit global data section
    if prog["globals"]:
        asm.append("    .data")
        for g in prog["globals"]:
            asm.append(f"    .globl {g['name']}")
            asm.append(f"{g['name']}:")
            asm.append(f"    .quad {g['init']}")
        asm.append("")

    # Emit text section with all functions
    asm.append("    .text")
    for func in prog["functions"]:
        asm.extend(compile_function(func))

    # Mark stack as non-executable (suppress linker warning)
    asm.append('    .section .note.GNU-stack,"",@progbits')

    return "\n".join(asm) + "\n"


if __name__ == "__main__":
    main()

"""Parser for .vasm (VLIW Assembly) format.

"""


def _parse_int(s):
    s = s.strip()
    if s.startswith('0x') or s.startswith('0X'):
        return int(s, 16)
    if s.startswith('-0x') or s.startswith('-0X'):
        return -int(s[1:], 16)
    return int(s)


def _parse_reg(s):
    s = s.strip()
    if s == '_':
        return -1
    if s.startswith('v') or s.startswith('p'):
        return int(s[1:])
    raise ValueError(f"Invalid register token: {s}")


def parse_vasm(text):
    """Parse a .vasm string into a program dict.

    Returns dict with keys:
        name, instructions, initial_memory, max_regs, max_cycles
    """
    meta = {}
    data = {}
    instructions = []

    for line in text.strip().split('\n'):
        line = line.split(';')[0].strip()
        if not line:
            continue

        if line.startswith('.meta'):
            parts = line.split(None, 2)
            meta[parts[1]] = parts[2]
        elif line.startswith('.data'):
            parts = line.split()
            data[_parse_int(parts[1])] = _parse_int(parts[2])
        else:
            inst = _parse_instruction(line)
            instructions.append(inst)

    return {
        "name": meta.get("name", "unnamed"),
        "instructions": instructions,
        "initial_memory": data,
        "max_regs": int(meta.get("max_regs", 32)),
        "max_cycles": int(meta.get("max_cycles", 100)),
    }


def _parse_instruction(line):
    tokens = line.split()
    op = tokens[0]

    if op == "halt":
        return {"op": "halt", "dst": -1, "srcs": []}

    if op == "const":
        dst = _parse_reg(tokens[1])
        imm = 0
        for t in tokens[2:]:
            if t.startswith('#'):
                imm = _parse_int(t[1:])
        return {"op": "const", "dst": dst, "srcs": [], "imm": imm}

    # General: op dst src1 [src2 [src3]]
    dst = _parse_reg(tokens[1])
    srcs = []
    for t in tokens[2:]:
        if t.startswith('#'):
            pass
        else:
            srcs.append(_parse_reg(t))

    inst = {"op": op, "dst": dst, "srcs": srcs}
    return inst

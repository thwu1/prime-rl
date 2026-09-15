
"""tiny-gpu assembler: converts assembly source to 16-bit machine code."""


def assemble(source: str) -> list:
    """Assemble tiny-gpu assembly source into a list of 16-bit instruction words."""
    lines = source.strip().split('\n')

    # First pass: collect labels, strip comments/directives, gather instructions
    labels = {}
    instructions = []
    for line in lines:
        # Remove comments
        line = line.split(';')[0].strip()
        if not line:
            continue
        # Skip assembler directives
        if line.startswith('.'):
            continue
        # Handle labels
        if ':' in line:
            idx = line.index(':')
            label = line[:idx].strip()
            labels[label] = len(instructions)
            rest = line[idx + 1:].strip()
            if rest:
                instructions.append(rest)
        else:
            instructions.append(line)

    # Second pass: encode each instruction
    return [_encode(inst, labels) for inst in instructions]


def _parse_reg(s: str) -> int:
    """Parse a register name and return its 4-bit index."""
    s = s.strip().strip(',')
    if s == '%blockIdx':
        return 13
    if s == '%blockDim':
        return 14
    if s == '%threadIdx':
        return 15
    if s.upper().startswith('R'):
        return int(s[1:])
    raise ValueError(f"Unknown register: {s}")


def _parse_imm(s: str) -> int:
    """Parse an immediate value (with or without # prefix)."""
    s = s.strip().strip(',')
    if s.startswith('#'):
        return int(s[1:])
    return int(s)


def _encode(inst: str, labels: dict) -> int:
    """Encode a single instruction into a 16-bit word."""
    parts = inst.replace(',', ' ').split()
    mn = parts[0].upper()

    if mn == 'NOP':
        return 0x0000

    if mn == 'RET':
        return 0xF000

    if mn.startswith('BR'):
        cond = mn[2:].upper()
        nzp = 0
        if 'N' in cond:
            nzp |= 4
        if 'Z' in cond:
            nzp |= 2
        if 'P' in cond:
            nzp |= 1
        target = parts[1].strip()
        imm = labels[target] if target in labels else _parse_imm(target)
        return (1 << 12) | (nzp << 9) | (imm & 0xFF)

    if mn == 'CMP':
        rs = _parse_reg(parts[1])
        rt = _parse_reg(parts[2])
        return (2 << 12) | (rs << 4) | rt

    if mn == 'ADD':
        rd = _parse_reg(parts[1])
        rs = _parse_reg(parts[2])
        rt = _parse_reg(parts[3])
        return (3 << 12) | (rd << 8) | (rs << 4) | rt

    if mn == 'SUB':
        rd = _parse_reg(parts[1])
        rs = _parse_reg(parts[2])
        rt = _parse_reg(parts[3])
        return (4 << 12) | (rd << 8) | (rs << 4) | rt

    if mn == 'MUL':
        rd = _parse_reg(parts[1])
        rs = _parse_reg(parts[2])
        rt = _parse_reg(parts[3])
        return (5 << 12) | (rd << 8) | (rs << 4) | rt

    if mn == 'DIV':
        rd = _parse_reg(parts[1])
        rs = _parse_reg(parts[2])
        rt = _parse_reg(parts[3])
        return (6 << 12) | (rd << 8) | (rs << 4) | rt

    if mn == 'LDR':
        rd = _parse_reg(parts[1])
        rs = _parse_reg(parts[2])
        return (7 << 12) | (rd << 8) | (rs << 4)

    if mn == 'STR':
        rs = _parse_reg(parts[1])
        rt = _parse_reg(parts[2])
        return (8 << 12) | (rs << 4) | rt

    if mn == 'CONST':
        rd = _parse_reg(parts[1])
        imm = _parse_imm(parts[2])
        return (9 << 12) | (rd << 8) | (imm & 0xFF)

    raise ValueError(f"Unknown instruction: {mn}")

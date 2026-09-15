"""
tiny-gpu assembler

Parses tiny-gpu assembly source text and produces 16-bit machine code.
Derives instruction encoding from the tiny-gpu Verilog decoder module.

Instruction format (16 bits):
  [15:12] opcode
  [11:8]  rd (destination register)
  [7:4]   rs (source register 1)
  [3:0]   rt (source register 2)
  [7:0]   immediate (for CONST, BRnzp)
  [11:9]  nzp condition (for BRnzp)

Operand mapping per instruction type:
  ADD/SUB/MUL/DIV Rd, Rs, Rt  -> rd=[11:8], rs=[7:4], rt=[3:0]
  CMP Rs, Rt                  -> rd=0, rs=[7:4], rt=[3:0]
  LDR Rd, Rs                  -> rd=[11:8], rs=[7:4], rt=0
  STR Rs, Rt                  -> rd=0, rs=[7:4], rt=[3:0]
  CONST Rd, #imm              -> rd=[11:8], imm=[7:0]
  BRx target                  -> nzp=[11:9], imm=[7:0]
  RET                         -> 0xF000
  NOP                         -> 0x0000
"""

OPCODES = {
    'NOP':   0b0000,
    'BRnzp': 0b0001,
    'BRn':   0b0001,
    'BRz':   0b0001,
    'BRp':   0b0001,
    'BRnz':  0b0001,
    'BRnp':  0b0001,
    'BRzp':  0b0001,
    'CMP':   0b0010,
    'ADD':   0b0011,
    'SUB':   0b0100,
    'MUL':   0b0101,
    'DIV':   0b0110,
    'LDR':   0b0111,
    'STR':   0b1000,
    'CONST': 0b1001,
    'RET':   0b1111,
}

NZP_BITS = {
    'BRn':   0b100,
    'BRz':   0b010,
    'BRp':   0b001,
    'BRnz':  0b110,
    'BRnp':  0b101,
    'BRzp':  0b011,
    'BRnzp': 0b111,
}

REGISTERS = {
    'R0': 0, 'R1': 1, 'R2': 2, 'R3': 3,
    'R4': 4, 'R5': 5, 'R6': 6, 'R7': 7,
    'R8': 8, 'R9': 9, 'R10': 10, 'R11': 11,
    'R12': 12,
    '%blockIdx': 13,
    '%blockDim': 14,
    '%threadIdx': 15,
}


def _parse_register(token):
    """Parse a register token, stripping trailing commas."""
    token = token.strip().rstrip(',')
    if token in REGISTERS:
        return REGISTERS[token]
    raise ValueError(f"Unknown register: {token}")


def _parse_immediate(token):
    """Parse an immediate value token (e.g., '#8' or '8')."""
    token = token.strip().rstrip(',')
    if token.startswith('#'):
        return int(token[1:])
    return int(token)


def assemble(source):
    """
    Assemble tiny-gpu assembly source into machine code.

    Args:
        source: Assembly source text.

    Returns:
        dict with keys:
            'program': list of 16-bit int machine code words
            'data': list of initial data memory values
            'threads': thread count from .threads directive
    """
    lines = source.strip().split('\n')

    threads = 0
    data = []
    labels = {}

    # First pass: strip comments, collect labels, identify instruction lines
    pc = 0
    cleaned = []
    for line in lines:
        # Remove comments
        comment_pos = line.find(';')
        if comment_pos >= 0:
            line = line[:comment_pos]
        line = line.strip()
        if not line:
            continue

        # Handle directives
        if line.startswith('.threads'):
            threads = int(line.split()[1])
            continue
        if line.startswith('.data'):
            values = line.split()[1:]
            data.extend(int(v) for v in values)
            continue

        # Handle labels
        if ':' in line:
            colon_pos = line.index(':')
            label = line[:colon_pos].strip()
            labels[label] = pc
            rest = line[colon_pos + 1:].strip()
            if rest:
                cleaned.append((pc, rest))
                pc += 1
            continue

        cleaned.append((pc, line))
        pc += 1

    # Second pass: encode instructions
    program = []
    for pc, line in cleaned:
        tokens = line.split()
        mnemonic = tokens[0]

        if mnemonic == 'NOP':
            program.append(0x0000)
        elif mnemonic == 'RET':
            program.append(0xF000)
        elif mnemonic in NZP_BITS:
            nzp = NZP_BITS[mnemonic]
            target_token = tokens[1].strip()
            if target_token in labels:
                target = labels[target_token]
            else:
                target = int(target_token)
            instr = (OPCODES[mnemonic] << 12) | (nzp << 9) | (target & 0xFF)
            program.append(instr)
        elif mnemonic == 'CMP':
            rs = _parse_register(tokens[1])
            rt = _parse_register(tokens[2])
            instr = (OPCODES['CMP'] << 12) | (rs << 4) | rt
            program.append(instr)
        elif mnemonic in ('ADD', 'SUB', 'MUL', 'DIV'):
            rd = _parse_register(tokens[1])
            rs = _parse_register(tokens[2])
            rt = _parse_register(tokens[3])
            instr = (OPCODES[mnemonic] << 12) | (rd << 8) | (rs << 4) | rt
            program.append(instr)
        elif mnemonic == 'LDR':
            rd = _parse_register(tokens[1])
            rs = _parse_register(tokens[2])
            instr = (OPCODES['LDR'] << 12) | (rd << 8) | (rs << 4)
            program.append(instr)
        elif mnemonic == 'STR':
            rs = _parse_register(tokens[1])
            rt = _parse_register(tokens[2])
            instr = (OPCODES['STR'] << 12) | (rs << 4) | rt
            program.append(instr)
        elif mnemonic == 'CONST':
            rd = _parse_register(tokens[1])
            imm = _parse_immediate(tokens[2])
            instr = (OPCODES['CONST'] << 12) | (rd << 8) | (imm & 0xFF)
            program.append(instr)
        else:
            raise ValueError(f"Unknown instruction: {mnemonic}")

    return {'program': program, 'data': data, 'threads': threads}

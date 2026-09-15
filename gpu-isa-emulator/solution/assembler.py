#!/usr/bin/env python3
"""
Assembler for the tiny-gpu ISA.

Translates tiny-gpu assembly language into 16-bit machine code.
Encoding derived from the SystemVerilog decoder at src/decoder.sv.

Instruction format (16 bits):
  [15:12] opcode
  [11:8]  rd  (destination register)
  [7:4]   rs  (source register 1)
  [3:0]   rt  (source register 2)
  [7:0]   immediate (for CONST, BRnzp)
  [11:9]  nzp condition (for BRnzp)

Opcodes (from decoder.sv localparam):
  NOP   = 0000    BRnzp = 0001    CMP   = 0010
  ADD   = 0011    SUB   = 0100    MUL   = 0101
  DIV   = 0110    LDR   = 0111    STR   = 1000
  CONST = 1001    RET   = 1111
"""


REGISTER_MAP = {
    'R0': 0, 'R1': 1, 'R2': 2, 'R3': 3,
    'R4': 4, 'R5': 5, 'R6': 6, 'R7': 7,
    'R8': 8, 'R9': 9, 'R10': 10, 'R11': 11,
    'R12': 12,
    '%BLOCKIDX': 13, '%BLOCKDIM': 14, '%THREADIDX': 15,
}

OPCODES = {
    'NOP': 0b0000,
    'CMP': 0b0010,
    'ADD': 0b0011,
    'SUB': 0b0100,
    'MUL': 0b0101,
    'DIV': 0b0110,
    'LDR': 0b0111,
    'STR': 0b1000,
    'CONST': 0b1001,
    'RET': 0b1111,
}


def _parse_register(token):
    """Parse a register token into its 4-bit index."""
    token = token.strip().rstrip(',').upper()
    if token.startswith('%'):
        token = '%' + token[1:]
        mapping = {
            '%BLOCKIDX': 13,
            '%BLOCKDIM': 14,
            '%THREADIDX': 15,
        }
        if token in mapping:
            return mapping[token]
    if token in REGISTER_MAP:
        return REGISTER_MAP[token]
    raise ValueError(f"Unknown register: {token}")


def assemble(source: str) -> list:
    """
    Assemble tiny-gpu assembly source into a list of 16-bit machine code integers.

    Args:
        source: Assembly source code as a string.

    Returns:
        List of 16-bit integers representing the machine code.
    """
    lines = source.strip().split('\n')

    # First pass: collect labels and build instruction list
    raw_instructions = []
    labels = {}

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
            parts = line.split(':', 1)
            label_name = parts[0].strip()
            labels[label_name] = len(raw_instructions)
            rest = parts[1].strip()
            if rest:
                raw_instructions.append(rest)
            continue
        raw_instructions.append(line)

    # Second pass: encode each instruction
    machine_code = []
    for inst_str in raw_instructions:
        tokens = inst_str.replace(',', ' ').split()
        mnemonic = tokens[0].upper()

        if mnemonic == 'NOP':
            machine_code.append(0)

        elif mnemonic == 'RET':
            machine_code.append(0b1111 << 12)

        elif mnemonic.startswith('BR'):
            # Parse branch condition from suffix (e.g., BRn -> n=1,z=0,p=0)
            suffix = mnemonic[2:].lower()
            n = 1 if 'n' in suffix else 0
            z = 1 if 'z' in suffix else 0
            p = 1 if 'p' in suffix else 0
            nzp = (n << 2) | (z << 1) | p

            target_label = tokens[1]
            if target_label in labels:
                target_addr = labels[target_label]
            else:
                target_addr = int(target_label)

            encoded = (0b0001 << 12) | (nzp << 9) | (target_addr & 0xFF)
            machine_code.append(encoded)

        elif mnemonic == 'CMP':
            rs = _parse_register(tokens[1])
            rt = _parse_register(tokens[2])
            encoded = (OPCODES['CMP'] << 12) | (rs << 4) | rt
            machine_code.append(encoded)

        elif mnemonic in ('ADD', 'SUB', 'MUL', 'DIV'):
            rd = _parse_register(tokens[1])
            rs = _parse_register(tokens[2])
            rt = _parse_register(tokens[3])
            opcode = OPCODES[mnemonic]
            encoded = (opcode << 12) | (rd << 8) | (rs << 4) | rt
            machine_code.append(encoded)

        elif mnemonic == 'LDR':
            rd = _parse_register(tokens[1])
            rs = _parse_register(tokens[2])
            encoded = (OPCODES['LDR'] << 12) | (rd << 8) | (rs << 4)
            machine_code.append(encoded)

        elif mnemonic == 'STR':
            rs = _parse_register(tokens[1])  # address register
            rt = _parse_register(tokens[2])  # data register
            encoded = (OPCODES['STR'] << 12) | (rs << 4) | rt
            machine_code.append(encoded)

        elif mnemonic == 'CONST':
            rd = _parse_register(tokens[1])
            imm_str = tokens[2].lstrip('#')
            imm = int(imm_str) & 0xFF
            encoded = (OPCODES['CONST'] << 12) | (rd << 8) | imm
            machine_code.append(encoded)

        else:
            raise ValueError(f"Unknown instruction: {mnemonic}")

    return machine_code

"""x86-64 assembly parser for decompilation matching."""
import re


def parse_assembly(filepath):
    """Parse an assembly file into list of (mnemonic, [operand_strings])."""
    instructions = []
    with open(filepath) as f:
        for line in f:
            line = line.split('#')[0].strip()
            if not line:
                continue
            if line.endswith(':'):
                continue
            if line.startswith('.'):
                continue
            parts = line.split(None, 1)
            mnemonic = parts[0]
            operands = _split_operands(parts[1]) if len(parts) > 1 else []
            instructions.append((mnemonic, operands))
    return instructions


def _split_operands(s):
    """Split operand string on commas, respecting parentheses."""
    result = []
    depth = 0
    current = []
    for ch in s:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            result.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        result.append(''.join(current).strip())
    return result


def extract_registers(operand):
    """Extract all register names from an operand string."""
    return re.findall(r'%\w+', operand)

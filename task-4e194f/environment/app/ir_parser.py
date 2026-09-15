
import re
from ir_types import Instruction, BasicBlock, Function, Program


def parse_arg(s):
    """Parse an argument as either an integer literal or a register name."""
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return s


def parse_program(source: str) -> Program:
    """Parse IR source text into a Program data structure."""
    program = Program()
    current_func = None
    current_block = None

    for line in source.split('\n'):
        # Strip comments
        if '#' in line:
            line = line[:line.index('#')]
        line = line.strip()
        if not line:
            continue

        # Function definition: func name(params):
        m = re.match(r'func\s+(\w+)\s*\(([^)]*)\)\s*:', line)
        if m:
            name = m.group(1)
            params_str = m.group(2).strip()
            params = [p.strip() for p in params_str.split(',') if p.strip()] if params_str else []
            current_func = Function(name=name, params=params)
            program.functions.append(current_func)
            current_block = None
            continue

        # Block label: .label:
        m = re.match(r'\.(\w+)\s*:', line)
        if m:
            label = m.group(1)
            current_block = BasicBlock(label=label)
            if current_func:
                current_func.blocks.append(current_block)
            continue

        if current_block is None:
            continue

        # cbr cond .true_label .false_label
        m = re.match(r'cbr\s+(\S+)\s+\.(\w+)\s+\.(\w+)', line)
        if m:
            cond = parse_arg(m.group(1))
            true_label = m.group(2)
            false_label = m.group(3)
            current_block.instructions.append(
                Instruction(op='cbr', args=[cond, true_label, false_label])
            )
            continue

        # br .label
        m = re.match(r'br\s+\.(\w+)', line)
        if m:
            current_block.instructions.append(
                Instruction(op='br', args=[m.group(1)])
            )
            continue

        # ret value
        m = re.match(r'ret\s+(\S+)', line)
        if m:
            current_block.instructions.append(
                Instruction(op='ret', args=[parse_arg(m.group(1))])
            )
            continue

        # print value
        m = re.match(r'print\s+(\S+)', line)
        if m:
            current_block.instructions.append(
                Instruction(op='print', args=[parse_arg(m.group(1))])
            )
            continue

        # nop
        if line == 'nop':
            current_block.instructions.append(Instruction(op='nop'))
            continue

        # Assignment: dest = op args...
        m = re.match(r'(\w+)\s*=\s*(\w+)\s*(.*)', line)
        if m:
            dest = m.group(1)
            op = m.group(2)
            args_str = m.group(3).strip()
            args = [parse_arg(a) for a in args_str.split() if a] if args_str else []
            current_block.instructions.append(
                Instruction(op=op, dest=dest, args=args)
            )
            continue

    return program

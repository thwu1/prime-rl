
from ir_types import Program, Function, BasicBlock, Instruction


def emit_instruction(instr: Instruction) -> str:
    """Emit a single instruction as IR text."""
    if instr.op == 'br':
        return f"    br .{instr.args[0]}"
    elif instr.op == 'cbr':
        return f"    cbr {instr.args[0]} .{instr.args[1]} .{instr.args[2]}"
    elif instr.op == 'ret':
        return f"    ret {instr.args[0]}"
    elif instr.op == 'print':
        return f"    print {instr.args[0]}"
    elif instr.op == 'nop':
        return "    nop"
    else:
        args_str = ' '.join(str(a) for a in instr.args)
        if args_str:
            return f"    {instr.dest} = {instr.op} {args_str}"
        return f"    {instr.dest} = {instr.op}"


def emit_block(block: BasicBlock) -> str:
    """Emit a basic block as IR text."""
    lines = [f"  .{block.label}:"]
    for instr in block.instructions:
        lines.append(emit_instruction(instr))
    return '\n'.join(lines)


def emit_function(func: Function) -> str:
    """Emit a function as IR text."""
    params_str = ', '.join(func.params)
    lines = [f"func {func.name}({params_str}):"]
    for block in func.blocks:
        lines.append(emit_block(block))
    return '\n'.join(lines)


def emit_program(program: Program) -> str:
    """Emit a complete program as IR text."""
    return '\n\n'.join(emit_function(f) for f in program.functions) + '\n'

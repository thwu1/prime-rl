"""
Emulator for the three-address code IR.

Executes a Program and returns the list of printed integer values.
Works with virtual registers, physical registers, and stack slots.
"""


from ir import Program


def emulate(program: Program, max_steps: int = 1_000_000) -> list:
    """
    Execute *program* and return the list of values output by PRINT
    instructions, in order.
    """
    program.validate()

    regs: dict = {}
    output: list = []
    label = program.entry
    idx = 0
    steps = 0

    while steps < max_steps:
        steps += 1
        instr = program.blocks[label][idx]
        op = instr.op

        if op == 'CONST':
            regs[instr.dst] = int(instr.src1)
            idx += 1

        elif op in ('ADD', 'SUB', 'MUL', 'MOD'):
            a = regs[instr.src1]
            b = regs[instr.src2]
            if op == 'ADD':
                regs[instr.dst] = a + b
            elif op == 'SUB':
                regs[instr.dst] = a - b
            elif op == 'MUL':
                regs[instr.dst] = a * b
            elif op == 'MOD':
                regs[instr.dst] = a % b
            idx += 1

        elif op in ('CMP_LT', 'CMP_EQ'):
            a = regs[instr.src1]
            b = regs[instr.src2]
            if op == 'CMP_LT':
                regs[instr.dst] = 1 if a < b else 0
            else:
                regs[instr.dst] = 1 if a == b else 0
            idx += 1

        elif op == 'MOV':
            regs[instr.dst] = regs[instr.src1]
            idx += 1

        elif op == 'PRINT':
            output.append(regs[instr.src1])
            idx += 1

        elif op == 'BR':
            if regs[instr.src1] != 0:
                label = instr.label1
            else:
                label = instr.label2
            idx = 0

        elif op == 'JMP':
            label = instr.label1
            idx = 0

        elif op == 'RET':
            return output

        else:
            raise RuntimeError(f"Unknown instruction: {instr}")

    raise RuntimeError("Exceeded maximum steps — possible infinite loop")

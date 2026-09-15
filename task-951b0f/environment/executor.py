"""Interpreter for pseudo-x86-64 CFGs.

Executes a CFG with either virtual or physical registers. Used by the test
suite to verify that register-allocated programs produce the same output
as their un-allocated counterparts.

"""
from ir import VReg, PReg, Imm, Deref, CFG


class ExecutionError(Exception):
    pass


class Executor:
    """Step-by-step interpreter for a pseudo-x86-64 CFG."""

    MAX_STEPS = 200_000           # safety cap against infinite loops

    def __init__(self, cfg: CFG, inputs: list | None = None):
        self.cfg       = cfg
        self.inputs    = list(inputs or [])
        self.input_idx = 0
        self.outputs   = []
        self.regs      = {}       # VReg | PReg  ->  int
        self.memory    = {}       # int (rbp offset) -> int
        self.flags     = {'ZF': False, 'SF': False, 'OF': False}

    # -- operand helpers ---------------------------------------------------

    def _get(self, operand):
        if isinstance(operand, Imm):
            return operand.value
        if isinstance(operand, (VReg, PReg)):
            return self.regs.get(operand, 0)
        if isinstance(operand, Deref):
            return self.memory.get(operand.offset, 0)
        raise ExecutionError(f"cannot read {operand!r}")

    def _set(self, operand, value):
        if isinstance(operand, (VReg, PReg)):
            self.regs[operand] = value
        elif isinstance(operand, Deref):
            self.memory[operand.offset] = value
        else:
            raise ExecutionError(f"cannot write to {operand!r}")

    # -- condition codes ---------------------------------------------------

    def _check_cc(self, cc: str) -> bool:
        zf = self.flags['ZF']
        sf = self.flags['SF']
        of = self.flags['OF']
        if cc == 'e':   return zf
        if cc == 'ne':  return not zf
        if cc == 'l':   return sf != of
        if cc == 'g':   return (not zf) and (sf == of)
        if cc == 'le':  return zf or (sf != of)
        if cc == 'ge':  return sf == of
        raise ExecutionError(f"unknown condition code: {cc}")

    # -- clobber helpers ---------------------------------------------------

    _CALLER_SAVED_NAMES = ('rax', 'rcx', 'rdx', 'rsi', 'rdi',
                           'r8', 'r9', 'r10', 'r11')

    def _clobber_caller_saved(self):
        """Write a poison value to all caller-saved registers."""
        for r in self._CALLER_SAVED_NAMES:
            self.regs[PReg(r)] = 0xDEAD_DEAD_DEAD

    # -- main loop ---------------------------------------------------------

    def run(self) -> list[int]:
        """Execute the CFG and return the list of printed integer values."""
        label = self.cfg.entry
        pc    = 0
        steps = 0

        while steps < self.MAX_STEPS:
            steps += 1
            block = self.cfg.blocks.get(label)
            if block is None:
                raise ExecutionError(f"block '{label}' not found")
            if pc >= len(block.instrs):
                raise ExecutionError(f"fell off end of block '{label}'")

            instr = block.instrs[pc]
            op    = instr.op
            args  = instr.args

            # -- data movement / arithmetic --------------------------------
            if op == 'movq':
                self._set(args[1], self._get(args[0]))
                pc += 1

            elif op == 'addq':
                self._set(args[1], self._get(args[1]) + self._get(args[0]))
                pc += 1

            elif op == 'subq':
                self._set(args[1], self._get(args[1]) - self._get(args[0]))
                pc += 1

            elif op == 'imulq':
                self._set(args[1], self._get(args[1]) * self._get(args[0]))
                pc += 1

            elif op == 'negq':
                self._set(args[0], -self._get(args[0]))
                pc += 1

            # -- comparison ------------------------------------------------
            elif op == 'cmpq':
                a = self._get(args[1])          # dst
                b = self._get(args[0])          # src
                diff = a - b
                self.flags['ZF'] = (diff == 0)
                self.flags['SF'] = (diff < 0)
                self.flags['OF'] = False        # simplified: no overflow
                pc += 1

            # -- calls -----------------------------------------------------
            elif op == 'callq':
                func = args[0]
                if func == 'read_int':
                    if self.input_idx >= len(self.inputs):
                        raise ExecutionError("no more input available")
                    val = self.inputs[self.input_idx]
                    self.input_idx += 1
                    self._clobber_caller_saved()
                    self.regs[PReg('rax')] = val      # return value
                elif func == 'print_int':
                    self.outputs.append(self._get(PReg('rdi')))
                    self._clobber_caller_saved()
                else:
                    raise ExecutionError(f"unknown function: {func}")
                pc += 1

            # -- control flow ----------------------------------------------
            elif op == 'retq':
                return self.outputs

            elif op == 'jmp':
                label = args[0]
                pc = 0

            elif op in ('je', 'jne', 'jl', 'jg', 'jle', 'jge'):
                cc = op[1:]                     # strip leading 'j'
                if self._check_cc(cc):
                    label = args[0]
                    pc = 0
                else:
                    pc += 1

            # -- stack (no-ops in interpreter) -----------------------------
            elif op in ('pushq', 'popq'):
                pc += 1

            else:
                raise ExecutionError(f"unknown instruction: {op}")

        raise ExecutionError("max steps exceeded — possible infinite loop")

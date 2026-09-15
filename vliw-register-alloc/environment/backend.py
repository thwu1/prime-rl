"""
VLIW Backend Compiler — stub.


Implement the `compile` function below.  It must transform a Program
(SSA-form instructions using virtual registers) into a CompiledProgram
(VLIW bundles using physical registers).

Requirements:
  1. Correctness — compiled program produces identical memory output
     as the sequential reference simulation.
  2. Register limit — uses at most `max_regs` physical registers.
     Register r0 is hardwired to zero.
  3. Performance — total cycle count (bundles + stall cycles) must be
     at most the target specified per test case.

Memory addresses >= program.data_size are available as scratch / spill
space (total memory is 256 words).
"""

from vliw import Program, CompiledProgram


def compile(program: Program, max_regs: int) -> CompiledProgram:
    """Compile *program* to VLIW bundles using at most *max_regs* registers."""
    raise NotImplementedError("Implement this function")

"""
x86-64 code generation from an allocated control flow graph.
"""
from typing import Dict
from cfg import CFG, Location, Var, Reg, Deref


def emit_x86(cfg: CFG, allocation: Dict[str, object]) -> str:
    """
    Generate x86-64 assembly (AT&T syntax) for the allocated program.

    Args:
        cfg: The control flow graph.
        allocation: Dict mapping variable names to assigned locations
                    (Reg or Deref objects from cfg module).

    Returns:
        String of x86-64 assembly defining a global function 'program'
        that returns its result in %rax. The assembly must be compilable
        with gcc (e.g., gcc -no-pie -o prog prog.s main.c).
    """
    raise NotImplementedError("Implement emit_x86")

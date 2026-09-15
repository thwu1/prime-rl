"""x86-64 assembly emitter — implement the ``emit_x86`` function.

"""
from ir import CFG


def emit_x86(cfg: CFG) -> str:
    """Generate GNU Assembler (GAS) x86-64 assembly for an allocated CFG.

    The input *cfg* contains only PReg, Imm, Deref, and str operands
    (no VRegs).  The returned assembly text must:

    - Define an externally visible ``main`` entry point.
    - Set up and tear down a proper stack frame.
    - Translate each IR instruction to its AT&T-syntax x86-64 equivalent.
    - Link correctly with ``/app/runtime.c`` when compiled via gcc.

    Returns the complete assembly source as a string.
    """
    raise NotImplementedError("Assembly emission not implemented.")

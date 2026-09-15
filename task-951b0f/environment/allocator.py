"""Register allocator — implement the ``allocate_registers`` function.

"""
from ir import CFG


def allocate_registers(cfg: CFG) -> CFG:
    """Replace all VReg operands in *cfg* with physical locations.

    The returned CFG must contain only PReg, Imm, and Deref operands
    and must be semantically equivalent to the original.
    """
    raise NotImplementedError("Register allocation not implemented.")

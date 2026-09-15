"""VLIW Optimizer — implement this module.

Your task: implement the optimize() function below.

See the vliwc tool for the machine model and assembly format:
    vliwc arch
    vliwc parse /app/programs/single_hash.vasm
    vliwc dump /app/programs/single_hash.vasm
"""



def optimize(instructions, max_regs):
    """Optimize a sequential instruction list for VLIW execution.

    Args:
        instructions: list of instruction dicts using virtual register numbers.
            Each dict has keys: "op", "dst", "srcs", and optionally "imm".
        max_regs: maximum number of physical registers (0 to max_regs-1).

    Returns:
        list of bundles, where each bundle is a list of instruction dicts
        using physical register numbers (0 to max_regs-1).
    """
    raise NotImplementedError("Implement your VLIW optimizer here")

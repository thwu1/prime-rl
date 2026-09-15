"""
VLIW Optimizer Stub

Implement the optimize() function below. It takes an SSA program with
virtual register names and produces VLIW instruction bundles using
physical register indices.

See /app/machine.py for the machine architecture specification.
See /app/machine.spec for slot constraints and latency definitions.
See /app/programs.py for the test programs.

This file must also work as a CLI tool:
  python3 optimizer.py <program_name>
  Outputs scheduled bundles in .vliw text format to stdout.
"""

from machine import LATENCY, SLOT_A_OPS, SLOT_B_OPS, SLOT_M_OPS


def optimize(instructions, num_regs, mem_size=4096):
    """
    Optimize an SSA program for the VLIW machine.

    Args:
        instructions: list of SSA instruction tuples. Each uses virtual
            register names (strings). Formats:
              ("ADD"|"SUB"|..., dest_vreg, src1_vreg, src2_vreg)
              ("MUL", dest_vreg, src1_vreg, src2_vreg)
              ("MOV", dest_vreg, src_vreg)
              ("MOVI", dest_vreg, immediate_int)
              ("LOAD", dest_vreg, addr_vreg)
              ("STORE", addr_vreg, val_vreg)
        num_regs: number of physical registers (r0 is always 0).
        mem_size: data memory size.

    Returns:
        list of VLIW bundles. Each bundle is a dict:
          {"SLOT_A": instr_or_None, "SLOT_B": instr_or_None, "SLOT_M": instr_or_None}
        where each instruction uses physical register indices (ints 0..num_regs-1):
          ("ADD", rd, rs1, rs2)
          ("MUL", rd, rs1, rs2)   -- SLOT_B only
          ("MOV", rd, rs)
          ("MOVI", rd, imm)
          ("LOAD", rd, rs_addr)
          ("STORE", rs_addr, rs_val)
    """
    raise NotImplementedError("Implement the VLIW optimizer")


# ================================================================
# CLI Interface
# ================================================================

if __name__ == "__main__":
    import sys
    from programs import PROGRAMS
    from machine import write_vliw

    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <program_name>", file=sys.stderr)
        sys.exit(1)

    _name = sys.argv[1]
    _prog = next((p for p in PROGRAMS if p["name"] == _name), None)
    if _prog is None:
        print(f"Unknown program: {_name}", file=sys.stderr)
        print(f"Available: {', '.join(p['name'] for p in PROGRAMS)}",
              file=sys.stderr)
        sys.exit(1)

    _bundles = optimize(_prog["instructions"], _prog["num_regs"])
    write_vliw(_bundles, _prog["num_regs"], sys.stdout)

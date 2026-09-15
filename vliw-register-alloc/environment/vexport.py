#!/usr/bin/env python3
"""
vexport - Export compiled VLIW programs to .vbin interchange format.


Usage:
    python3 vexport.py <program_name> <output.vbin>
    python3 vexport.py --all <output_dir>
    python3 vexport.py --help

Available programs: smoke, scheduling, pressure, mixed

The .vbin format is a text-based interchange format readable by vsim.
See vsim.c header for full format specification.
"""
import sys
import os

sys.path.insert(0, "/app")


def show_help():
    print(__doc__.strip())
    sys.exit(0)


def export_program(name, program, max_regs, output_path):
    from backend import compile
    compiled = compile(program, max_regs)

    with open(output_path, "w") as f:
        f.write(f"# VLIW Binary - {name}\n")
        f.write(f"REGS {compiled.num_phys_regs}\n")
        f.write(f"DATASIZE {program.data_size}\n")
        for i, val in enumerate(program.init_mem):
            if val != 0:
                f.write(f"INIT {i} {val}\n")
        for bundle in compiled.bundles:
            f.write("BUNDLE\n")
            for slot_name in ("alu0", "alu1", "mul", "mem"):
                inst = getattr(bundle, slot_name)
                if inst is None:
                    f.write(f"{slot_name} nop\n")
                else:
                    srcs = list(inst.srcs) + [0, 0, 0]
                    dst = max(inst.dst, 0)
                    f.write(f"{slot_name} {inst.op} {dst} "
                            f"{srcs[0]} {srcs[1]} {srcs[2]} {inst.imm}\n")
            f.write("ENDBUNDLE\n")
        f.write("END\n")


if __name__ == "__main__":
    if len(sys.argv) < 2 or "--help" in sys.argv or "-h" in sys.argv:
        show_help()

    from programs import get_test_cases
    cases = {n: (p, mr, tc) for n, p, mr, tc in get_test_cases()}

    if sys.argv[1] == "--all":
        if len(sys.argv) < 3:
            print("Usage: vexport.py --all <output_dir>", file=sys.stderr)
            sys.exit(1)
        outdir = sys.argv[2]
        os.makedirs(outdir, exist_ok=True)
        for name, (prog, mr, tc) in cases.items():
            outpath = os.path.join(outdir, f"{name}.vbin")
            export_program(name, prog, mr, outpath)
            print(f"Exported {name} -> {outpath}")
    else:
        name = sys.argv[1]
        if name not in cases:
            avail = ", ".join(cases.keys())
            print(f"Unknown program: {name}. Available: {avail}",
                  file=sys.stderr)
            sys.exit(1)
        if len(sys.argv) < 3:
            print("Usage: vexport.py <program_name> <output.vbin>",
                  file=sys.stderr)
            sys.exit(1)
        prog, mr, tc = cases[name]
        export_program(name, prog, mr, sys.argv[2])
        print(f"Exported {name} -> {sys.argv[2]}")

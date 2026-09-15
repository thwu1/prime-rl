#!/usr/bin/env python3
"""
vdot - Generate Graphviz DOT dependency graphs from .vbin files.


Usage:
    python3 vdot.py <input.vbin>             Output DOT to stdout
    python3 vdot.py --help

Pipe output to graphviz to render:
    python3 vdot.py prog.vbin | dot -Tsvg -o prog.svg

The graph groups instructions by bundle (one cluster per bundle)
and shows register data-flow dependencies as edges.
"""
import sys


def show_help():
    print(__doc__.strip())
    sys.exit(0)


def parse_vbin(path):
    """Parse a .vbin file into a list of bundles (each a list of insts)."""
    bundles = []
    current = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line == "BUNDLE":
                current = []
            elif line == "ENDBUNDLE":
                if current is not None:
                    bundles.append(current)
                current = None
            elif line == "END":
                break
            elif current is not None:
                parts = line.split()
                if len(parts) >= 2 and parts[1] != "nop":
                    current.append({
                        "slot": parts[0],
                        "op": parts[1],
                        "dst": int(parts[2]) if len(parts) > 2 else 0,
                        "srcs": [
                            int(parts[3]) if len(parts) > 3 else 0,
                            int(parts[4]) if len(parts) > 4 else 0,
                            int(parts[5]) if len(parts) > 5 else 0,
                        ],
                        "imm": int(parts[6]) if len(parts) > 6 else 0,
                    })
    return bundles


def generate_dot(bundles):
    """Print a DOT graph to stdout."""
    lines = ["digraph vliw_schedule {"]
    lines.append("  rankdir=TB;")
    lines.append('  node [shape=record, fontsize=10];')
    lines.append('  edge [fontsize=8];')
    lines.append("")

    writers = {}  # reg -> (bundle_idx, slot_name)

    for bi, bundle in enumerate(bundles):
        lines.append(f"  subgraph cluster_b{bi} {{")
        lines.append(f'    label="Bundle {bi}";')
        lines.append("    style=dashed; color=gray;")
        for inst in bundle:
            nid = f"b{bi}_{inst['slot']}"
            if inst["op"] in ("lw", "sw"):
                lbl = f"{inst['slot']}: {inst['op']} [imm={inst['imm']}]"
            elif inst["op"] == "li":
                lbl = f"{inst['slot']}: li r{inst['dst']}={inst['imm']}"
            else:
                lbl = f"{inst['slot']}: {inst['op']} r{inst['dst']}"
            # Escape for DOT
            lbl = lbl.replace('"', '\\"')
            lines.append(f'    {nid} [label="{lbl}"];')
        lines.append("  }")

        # Add dependency edges from prior writers
        for inst in bundle:
            nid = f"b{bi}_{inst['slot']}"
            for src in inst["srcs"]:
                if src > 0 and src in writers:
                    sbi, sslot = writers[src]
                    sid = f"b{sbi}_{sslot}"
                    lines.append(f'  {sid} -> {nid} [label="r{src}"];')

            # Update writer map
            if inst["dst"] > 0:
                writers[inst["dst"]] = (bi, inst["slot"])

    lines.append("}")
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 2 or "--help" in sys.argv or "-h" in sys.argv:
        show_help()
    bundles = parse_vbin(sys.argv[1])
    generate_dot(bundles)

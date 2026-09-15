"""
VLIW Processor Simulator and Toolchain

Architecture:
  3 execution slots per bundle:
    SLOT_A - ALU ops: ADD, SUB, AND, OR, XOR, SHL, SHR, MOV, MOVI
    SLOT_B - ALU ops + MUL (MUL only here)
    SLOT_M - Memory ops: LOAD, STORE

  Physical register file of configurable size. Register 0 is hardwired to 0.
  All values are 32-bit unsigned integers.

Instruction formats:
  ("ADD"|"SUB"|"AND"|"OR"|"XOR"|"SHL"|"SHR", rd, rs1, rs2)
  ("MUL", rd, rs1, rs2)       -- SLOT_B only
  ("MOV", rd, rs)
  ("MOVI", rd, immediate)     -- 32-bit unsigned immediate
  ("LOAD", rd, rs_addr)       -- rd = mem[regs[rs_addr]]
  ("STORE", rs_addr, rs_val)  -- mem[regs[rs_addr]] = regs[rs_val]

Latencies (cycles until result is readable):
  ALU/MOV/MOVI = 1, MUL = 2, LOAD = 3, STORE = 1 (no dest register)

Hazard model:
  At start of each cycle, pending writes whose ready_cycle <= current_cycle
  are resolved. Reading a register with an unresolved pending write is a
  RAW hazard error. Two writes to the same register in the same bundle
  is a WAW hazard error.

CLI usage:
  python3 machine.py reference <program_name>
  python3 machine.py simulate <file.vliw> --init <program_name> [--trace]
  python3 machine.py compare <file.vliw> <program_name>
"""

MASK32 = 0xFFFFFFFF

SLOT_A_OPS = frozenset({"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MOV", "MOVI"})
SLOT_B_OPS = frozenset({"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MOV", "MOVI", "MUL"})
SLOT_M_OPS = frozenset({"LOAD", "STORE"})

LATENCY = {
    "ADD": 1, "SUB": 1, "AND": 1, "OR": 1, "XOR": 1,
    "SHL": 1, "SHR": 1, "MOV": 1, "MOVI": 1,
    "MUL": 2, "LOAD": 3, "STORE": 1,
}


def alu_exec(op, a, b):
    if op == "ADD": return (a + b) & MASK32
    if op == "SUB": return (a - b) & MASK32
    if op == "MUL": return (a * b) & MASK32
    if op == "AND": return a & b
    if op == "OR":  return a | b
    if op == "XOR": return a ^ b
    if op == "SHL": return (a << (b & 31)) & MASK32
    if op == "SHR": return a >> (b & 31)
    raise ValueError(f"Unknown ALU op: {op}")


class VLIWMachine:
    """Simulates VLIW execution of instruction bundles."""

    def __init__(self, num_regs=24, mem_size=4096):
        self.num_regs = num_regs
        self.regs = [0] * num_regs
        self.mem = [0] * mem_size
        self.pending = []  # list of (ready_cycle, reg_index, value)
        self.cycle = 0

    def _resolve(self):
        keep = []
        for rc, r, v in self.pending:
            if rc <= self.cycle:
                if r != 0:
                    self.regs[r] = v
            else:
                keep.append((rc, r, v))
        self.pending = keep

    def _has_hazard(self, r):
        if r == 0:
            return False
        return any(reg == r and rc > self.cycle for rc, reg, _ in self.pending)

    def _schedule_write(self, r, v, latency):
        if r != 0:
            self.pending.append((self.cycle + latency, r, v & MASK32))

    def step(self, bundle):
        """Execute one VLIW bundle. Raises on hazard violations."""
        self._resolve()

        # Check for WAW conflicts within the bundle
        dests = []
        for slot_name in ["SLOT_A", "SLOT_B", "SLOT_M"]:
            instr = bundle.get(slot_name)
            if instr is None:
                continue
            op = instr[0]
            if op not in ("STORE",):
                dests.append(instr[1])
        if len(dests) != len(set(dests)):
            raise RuntimeError(f"WAW conflict in bundle at cycle {self.cycle}: "
                               f"multiple writes to same register {dests}")

        for slot_name, allowed in [("SLOT_A", SLOT_A_OPS),
                                   ("SLOT_B", SLOT_B_OPS),
                                   ("SLOT_M", SLOT_M_OPS)]:
            instr = bundle.get(slot_name)
            if instr is None:
                continue
            op = instr[0]
            if op not in allowed:
                raise ValueError(f"Op {op} not allowed in {slot_name} at cycle {self.cycle}")

            if op in {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MUL"}:
                rd, rs1, rs2 = instr[1], instr[2], instr[3]
                assert 0 <= rd < self.num_regs, f"reg {rd} out of range"
                assert 0 <= rs1 < self.num_regs, f"reg {rs1} out of range"
                assert 0 <= rs2 < self.num_regs, f"reg {rs2} out of range"
                if self._has_hazard(rs1) or self._has_hazard(rs2):
                    raise RuntimeError(
                        f"RAW hazard at cycle {self.cycle}: {instr}, "
                        f"r{rs1} hazard={self._has_hazard(rs1)}, "
                        f"r{rs2} hazard={self._has_hazard(rs2)}")
                self._schedule_write(rd, alu_exec(op, self.regs[rs1], self.regs[rs2]),
                                     LATENCY[op])

            elif op == "MOV":
                rd, rs = instr[1], instr[2]
                assert 0 <= rd < self.num_regs and 0 <= rs < self.num_regs
                if self._has_hazard(rs):
                    raise RuntimeError(f"RAW hazard at cycle {self.cycle}: {instr}")
                self._schedule_write(rd, self.regs[rs], LATENCY["MOV"])

            elif op == "MOVI":
                rd, imm = instr[1], instr[2]
                assert 0 <= rd < self.num_regs
                self._schedule_write(rd, imm, LATENCY["MOVI"])

            elif op == "LOAD":
                rd, rs_addr = instr[1], instr[2]
                assert 0 <= rd < self.num_regs and 0 <= rs_addr < self.num_regs
                if self._has_hazard(rs_addr):
                    raise RuntimeError(f"RAW hazard at cycle {self.cycle}: {instr}")
                addr = self.regs[rs_addr] % len(self.mem)
                self._schedule_write(rd, self.mem[addr], LATENCY["LOAD"])

            elif op == "STORE":
                rs_addr, rs_val = instr[1], instr[2]
                assert 0 <= rs_addr < self.num_regs and 0 <= rs_val < self.num_regs
                if self._has_hazard(rs_addr) or self._has_hazard(rs_val):
                    raise RuntimeError(f"RAW hazard at cycle {self.cycle}: {instr}")
                addr = self.regs[rs_addr] % len(self.mem)
                self.mem[addr] = self.regs[rs_val]

        self.cycle += 1

    def drain(self):
        """Resolve all pending writes."""
        while self.pending:
            self.cycle += 1
            self._resolve()

    def run(self, bundles):
        """Execute a list of VLIW bundles and drain the pipeline."""
        for b in bundles:
            self.step(b)
        self.drain()
        return self.cycle


def reference_run(instructions, initial_mem=None, mem_size=4096):
    """
    Execute an SSA program sequentially as the golden reference.

    Args:
        instructions: list of SSA instruction tuples using virtual register names.
        initial_mem: dict mapping address -> value for memory initialization.
        mem_size: total memory size.

    Returns:
        Final memory state as a list.
    """
    vregs = {}
    mem = [0] * mem_size
    if initial_mem:
        for addr, val in initial_mem.items():
            mem[int(addr)] = val & MASK32

    def v(name):
        return vregs.get(name, 0)

    for instr in instructions:
        op = instr[0]
        if op in {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MUL"}:
            vregs[instr[1]] = alu_exec(op, v(instr[2]), v(instr[3]))
        elif op == "MOV":
            vregs[instr[1]] = v(instr[2])
        elif op == "MOVI":
            vregs[instr[1]] = instr[2] & MASK32
        elif op == "LOAD":
            addr = v(instr[2]) % len(mem)
            vregs[instr[1]] = mem[addr]
        elif op == "STORE":
            addr = v(instr[1]) % len(mem)
            mem[addr] = v(instr[2])

    return mem


def validate_bundles(bundles, num_regs):
    """
    Check that bundles are structurally valid (correct ops per slot,
    register indices in range, no WAW within a bundle).
    """
    for i, bundle in enumerate(bundles):
        dests = []
        for slot_name, allowed in [("SLOT_A", SLOT_A_OPS),
                                   ("SLOT_B", SLOT_B_OPS),
                                   ("SLOT_M", SLOT_M_OPS)]:
            instr = bundle.get(slot_name)
            if instr is None:
                continue
            op = instr[0]
            assert op in allowed, f"Bundle {i}: {op} not in {slot_name}"

            if op in {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MUL"}:
                rd, rs1, rs2 = instr[1], instr[2], instr[3]
                for r in (rd, rs1, rs2):
                    assert 0 <= r < num_regs, f"Bundle {i}: reg {r} out of range"
                dests.append(rd)
            elif op == "MOV":
                rd, rs = instr[1], instr[2]
                for r in (rd, rs):
                    assert 0 <= r < num_regs, f"Bundle {i}: reg {r} out of range"
                dests.append(rd)
            elif op == "MOVI":
                rd = instr[1]
                assert 0 <= rd < num_regs, f"Bundle {i}: reg {rd} out of range"
                dests.append(rd)
            elif op == "LOAD":
                rd, rs = instr[1], instr[2]
                for r in (rd, rs):
                    assert 0 <= r < num_regs, f"Bundle {i}: reg {r} out of range"
                dests.append(rd)
            elif op == "STORE":
                ra, rv = instr[1], instr[2]
                for r in (ra, rv):
                    assert 0 <= r < num_regs, f"Bundle {i}: reg {r} out of range"

        non_zero_dests = [d for d in dests if d != 0]
        assert len(non_zero_dests) == len(set(non_zero_dests)), \
            f"Bundle {i}: WAW conflict, dest regs = {dests}"


# ================================================================
# .vliw Text Format I/O
# ================================================================

def write_vliw(bundles, num_regs, stream=None, mem_size=4096):
    """Write VLIW bundles in .vliw text format to stream (default stdout)."""
    import sys as _sys
    out = stream or _sys.stdout
    out.write(f"NUM_REGS {num_regs}\n")
    out.write(f"MEM_SIZE {mem_size}\n\n")
    for i, bundle in enumerate(bundles):
        out.write(f"BUNDLE {i}\n")
        for slot_key in ["SLOT_A", "SLOT_B", "SLOT_M"]:
            letter = slot_key[-1]
            instr = bundle.get(slot_key)
            if instr is None:
                out.write(f"  {letter}: NOP\n")
            else:
                op = instr[0]
                if op in {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MUL"}:
                    out.write(f"  {letter}: {op} r{instr[1]} r{instr[2]} r{instr[3]}\n")
                elif op == "MOV":
                    out.write(f"  {letter}: MOV r{instr[1]} r{instr[2]}\n")
                elif op == "MOVI":
                    out.write(f"  {letter}: MOVI r{instr[1]} {instr[2]}\n")
                elif op == "LOAD":
                    out.write(f"  {letter}: LOAD r{instr[1]} r{instr[2]}\n")
                elif op == "STORE":
                    out.write(f"  {letter}: STORE r{instr[1]} r{instr[2]}\n")
        out.write("\n")


def read_vliw(stream):
    """Read .vliw text format, returning (bundles, num_regs, mem_size)."""
    num_regs = 24
    mem_size = 4096
    bundles = []
    current = None

    for line in stream:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("NUM_REGS"):
            num_regs = int(line.split()[1])
        elif line.startswith("MEM_SIZE"):
            mem_size = int(line.split()[1])
        elif line.startswith("BUNDLE"):
            if current is not None:
                bundles.append(current)
            current = {"SLOT_A": None, "SLOT_B": None, "SLOT_M": None}
        elif ":" in line and current is not None:
            parts = line.split(":", 1)
            letter = parts[0].strip()
            rest = parts[1].strip()
            slot_key = f"SLOT_{letter}"
            if slot_key not in current:
                continue
            if rest == "NOP":
                current[slot_key] = None
            else:
                tokens = rest.split()
                op = tokens[0]
                if op in {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MUL"}:
                    current[slot_key] = (op, int(tokens[1][1:]),
                                         int(tokens[2][1:]), int(tokens[3][1:]))
                elif op == "MOV":
                    current[slot_key] = (op, int(tokens[1][1:]),
                                         int(tokens[2][1:]))
                elif op == "MOVI":
                    current[slot_key] = (op, int(tokens[1][1:]),
                                         int(tokens[2], 0))
                elif op == "LOAD":
                    current[slot_key] = (op, int(tokens[1][1:]),
                                         int(tokens[2][1:]))
                elif op == "STORE":
                    current[slot_key] = (op, int(tokens[1][1:]),
                                         int(tokens[2][1:]))

    if current is not None:
        bundles.append(current)
    return bundles, num_regs, mem_size


# ================================================================
# CLI Interface
# ================================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="VLIW Machine Simulator CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Commands:\n"
            "  reference <prog>                    "
            "Run sequential reference, print check memory\n"
            "  simulate <f.vliw> --init <prog>     "
            "Simulate bundles, print results\n"
            "  compare <f.vliw> <prog>             "
            "Compare simulation against reference\n"))
    sub = parser.add_subparsers(dest="cmd")

    p1 = sub.add_parser("reference",
                        help="Run sequential reference execution")
    p1.add_argument("program", help="Program name from programs.py")

    p2 = sub.add_parser("simulate",
                        help="Simulate .vliw bundles on the machine")
    p2.add_argument("vliw_file", help="Path to .vliw bundle file")
    p2.add_argument("--init", required=True,
                    help="Program name for initial memory")
    p2.add_argument("--trace", action="store_true",
                    help="Print cycle-by-cycle execution trace")

    p3 = sub.add_parser("compare",
                        help="Compare simulation output with reference")
    p3.add_argument("vliw_file", help="Path to .vliw bundle file")
    p3.add_argument("program", help="Program name")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    from programs import PROGRAMS

    def _find(name):
        r = next((p for p in PROGRAMS if p["name"] == name), None)
        if not r:
            print(f"Unknown program: {name}", file=sys.stderr)
            avail = ", ".join(p["name"] for p in PROGRAMS)
            print(f"Available: {avail}", file=sys.stderr)
            sys.exit(1)
        return r

    if args.cmd == "reference":
        prog = _find(args.program)
        mem = reference_run(prog["instructions"],
                            prog.get("initial_mem", {}))
        for addr in sorted(prog["check_addrs"]):
            print(f"MEM[{addr}] = 0x{mem[addr]:08x}")

    elif args.cmd == "simulate":
        prog = _find(args.init)
        with open(args.vliw_file) as fh:
            bundles, _nr, _ms = read_vliw(fh)
        m = VLIWMachine(num_regs=prog["num_regs"], mem_size=4096)
        for addr, val in prog.get("initial_mem", {}).items():
            m.mem[int(addr)] = val & MASK32
        if args.trace:
            for i, b in enumerate(bundles):
                desc = []
                for s in ["SLOT_A", "SLOT_B", "SLOT_M"]:
                    ins = b.get(s)
                    desc.append(f"{s[-1]}:{ins[0] if ins else 'NOP'}")
                m.step(b)
                print(f"cycle {i:3d}: {' | '.join(desc)}  "
                      f"pending={len(m.pending)}")
            m.drain()
        else:
            m.run(bundles)
        for addr in sorted(prog["check_addrs"]):
            print(f"MEM[{addr}] = 0x{m.mem[addr]:08x}")
        print(f"CYCLES = {m.cycle}")
        print(f"TARGET = {prog['target_cycles']}")

    elif args.cmd == "compare":
        prog = _find(args.program)
        ref_mem = reference_run(prog["instructions"],
                                prog.get("initial_mem", {}))
        with open(args.vliw_file) as fh:
            bundles, _nr, _ms = read_vliw(fh)
        m = VLIWMachine(num_regs=prog["num_regs"], mem_size=4096)
        for addr, val in prog.get("initial_mem", {}).items():
            m.mem[int(addr)] = val & MASK32
        try:
            m.run(bundles)
        except (RuntimeError, AssertionError) as e:
            print(f"FAIL: simulation error: {e}")
            sys.exit(1)
        ok = True
        for addr in sorted(prog["check_addrs"]):
            actual = m.mem[addr]
            expected = ref_mem[addr]
            if actual != expected:
                print(f"MISMATCH MEM[{addr}]: "
                      f"got 0x{actual:08x}, expected 0x{expected:08x}")
                ok = False
        if m.cycle > prog["target_cycles"]:
            print(f"CYCLES {m.cycle} > TARGET {prog['target_cycles']}")
            ok = False
        if ok:
            print(f"PASS (cycles={m.cycle}, "
                  f"target={prog['target_cycles']})")
        else:
            print("FAIL")
            sys.exit(1)

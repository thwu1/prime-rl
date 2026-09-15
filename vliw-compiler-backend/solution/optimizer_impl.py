"""
VLIW Optimizer — Reference Solution

Implements register allocation and instruction scheduling for the VLIW machine.

Algorithm:
  1. Parse SSA instructions to extract def-use information.
  2. Build a dependency DAG (data deps + conservative memory ordering).
  3. Compute critical-path priorities for list scheduling.
  4. List-schedule instructions into cycles, packing up to 3 per VLIW bundle.
  5. Compute live ranges from the schedule.
  6. Linear-scan register allocation.
  7. Emit VLIW bundles with physical registers.
"""

import sys
from collections import deque

sys.path.insert(0, "/app")
from machine import LATENCY, SLOT_A_OPS, SLOT_B_OPS, SLOT_M_OPS


def optimize(instructions, num_regs, mem_size=4096):
    n = len(instructions)
    if n == 0:
        return []

    # ------------------------------------------------------------------ #
    # Step 1: Parse instructions                                          #
    # ------------------------------------------------------------------ #
    dest = [None] * n          # vreg defined by instruction i (or None)
    uses_list = [[] for _ in range(n)]  # vregs read by instruction i
    defs = {}                  # vreg name -> defining instruction index

    for i, instr in enumerate(instructions):
        op = instr[0]
        if op in {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MUL"}:
            dest[i] = instr[1]
            uses_list[i] = [instr[2], instr[3]]
        elif op == "MOV":
            dest[i] = instr[1]
            uses_list[i] = [instr[2]]
        elif op == "MOVI":
            dest[i] = instr[1]
            uses_list[i] = []
        elif op == "LOAD":
            dest[i] = instr[1]
            uses_list[i] = [instr[2]]
        elif op == "STORE":
            dest[i] = None
            uses_list[i] = [instr[1], instr[2]]

        if dest[i] is not None:
            defs[dest[i]] = i

    # ------------------------------------------------------------------ #
    # Step 2: Build dependency DAG                                        #
    # ------------------------------------------------------------------ #
    dep = [set() for _ in range(n)]   # predecessors
    succ = [set() for _ in range(n)]  # successors

    # Data dependencies (RAW)
    for i in range(n):
        for vreg in uses_list[i]:
            if vreg in defs:
                j = defs[vreg]
                if j != i:
                    dep[i].add(j)
                    succ[j].add(i)

    # Conservative memory ordering:
    #   - Each LOAD depends on all preceding STOREs
    #   - Each STORE depends on all preceding STOREs
    # This allows LOADs to be freely reordered w.r.t. each other.
    last_store = -1
    for i in range(n):
        op = instructions[i][0]
        if op == "LOAD":
            if last_store >= 0:
                dep[i].add(last_store)
                succ[last_store].add(i)
        elif op == "STORE":
            if last_store >= 0:
                dep[i].add(last_store)
                succ[last_store].add(i)
            last_store = i

    # ------------------------------------------------------------------ #
    # Step 3: Compute critical-path lengths                               #
    # ------------------------------------------------------------------ #
    # Process nodes from sinks to sources (reverse topological order).
    out_deg = [len(succ[i]) for i in range(n)]
    rev_topo = []
    queue = deque(i for i in range(n) if out_deg[i] == 0)
    tmp_out = list(out_deg)
    while queue:
        node = queue.popleft()
        rev_topo.append(node)
        for p in dep[node]:
            tmp_out[p] -= 1
            if tmp_out[p] == 0:
                queue.append(p)

    crit = [0] * n
    for node in rev_topo:
        op = instructions[node][0]
        lat = LATENCY.get(op, 1)
        max_s = max((crit[s] for s in succ[node]), default=0)
        crit[node] = lat + max_s

    # ------------------------------------------------------------------ #
    # Step 4: List scheduling                                             #
    # ------------------------------------------------------------------ #
    sched_cycle = [None] * n
    sched_slot = [None] * n
    avail = {}  # instruction index -> cycle when its result is readable

    rem_dep = [len(dep[i]) for i in range(n)]
    ready = set(i for i in range(n) if rem_dep[i] == 0)

    cycle = 0
    scheduled_count = 0
    max_iterations = n * 200  # safety limit
    iteration = 0

    while scheduled_count < n:
        iteration += 1
        if iteration > max_iterations:
            raise RuntimeError("Scheduling failed: exceeded iteration limit")

        # Find instructions ready to execute this cycle
        can_exec = []
        for i in ready:
            earliest = 0
            for d in dep[i]:
                if d in avail:
                    earliest = max(earliest, avail[d])
            if earliest <= cycle:
                can_exec.append(i)

        if not can_exec:
            cycle += 1
            continue

        # Sort by critical path (descending) for priority
        can_exec.sort(key=lambda i: -crit[i])

        # Assign to slots greedily
        slot_a_used = False
        slot_b_used = False
        slot_m_used = False

        for i in can_exec:
            op = instructions[i][0]
            slot = None

            if op in SLOT_M_OPS:
                if not slot_m_used:
                    slot = "SLOT_M"
                    slot_m_used = True
            elif op == "MUL":
                if not slot_b_used:
                    slot = "SLOT_B"
                    slot_b_used = True
            else:
                # General ALU ops: prefer SLOT_A, fall back to SLOT_B
                if not slot_a_used:
                    slot = "SLOT_A"
                    slot_a_used = True
                elif not slot_b_used:
                    slot = "SLOT_B"
                    slot_b_used = True

            if slot is not None:
                sched_cycle[i] = cycle
                sched_slot[i] = slot
                avail[i] = cycle + LATENCY.get(op, 1)
                ready.discard(i)
                scheduled_count += 1

                for s in succ[i]:
                    rem_dep[s] -= 1
                    if rem_dep[s] == 0:
                        ready.add(s)

        cycle += 1

    # ------------------------------------------------------------------ #
    # Step 5: Compute live ranges                                         #
    # ------------------------------------------------------------------ #
    live_start = {}  # vreg -> cycle defined
    live_end = {}    # vreg -> cycle of last use

    for i in range(n):
        if dest[i] is not None:
            v = dest[i]
            live_start[v] = sched_cycle[i]
            live_end[v] = sched_cycle[i]

    for i in range(n):
        for v in uses_list[i]:
            if v in live_end:
                live_end[v] = max(live_end[v], sched_cycle[i])

    # ------------------------------------------------------------------ #
    # Step 6: Linear-scan register allocation                             #
    # ------------------------------------------------------------------ #
    vregs_sorted = sorted(live_start.keys(),
                          key=lambda v: (live_start[v], live_end[v]))

    vreg_to_preg = {}
    active = []        # list of (end_cycle, preg)
    free = list(range(1, num_regs))  # r0 is reserved

    for v in vregs_sorted:
        start = live_start[v]

        # Free expired registers
        new_active = []
        for end, preg in active:
            if end < start:
                free.append(preg)
            else:
                new_active.append((end, preg))
        active = new_active
        free.sort()

        if not free:
            raise RuntimeError(
                f"Out of registers allocating {v} at cycle {start}. "
                f"Active: {len(active)}, needed: {num_regs}")
        preg = free.pop(0)
        vreg_to_preg[v] = preg
        active.append((live_end[v], preg))

    # ------------------------------------------------------------------ #
    # Step 7: Emit VLIW bundles                                           #
    # ------------------------------------------------------------------ #
    max_cyc = max(sched_cycle)
    bundles = [{"SLOT_A": None, "SLOT_B": None, "SLOT_M": None}
               for _ in range(max_cyc + 1)]

    for i in range(n):
        c = sched_cycle[i]
        s = sched_slot[i]
        instr = instructions[i]
        op = instr[0]

        if op in {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "MUL"}:
            bundles[c][s] = (op,
                             vreg_to_preg[instr[1]],
                             vreg_to_preg[instr[2]],
                             vreg_to_preg[instr[3]])
        elif op == "MOV":
            bundles[c][s] = ("MOV",
                             vreg_to_preg[instr[1]],
                             vreg_to_preg[instr[2]])
        elif op == "MOVI":
            bundles[c][s] = ("MOVI",
                             vreg_to_preg[instr[1]],
                             instr[2])
        elif op == "LOAD":
            bundles[c][s] = ("LOAD",
                             vreg_to_preg[instr[1]],
                             vreg_to_preg[instr[2]])
        elif op == "STORE":
            bundles[c][s] = ("STORE",
                             vreg_to_preg[instr[1]],
                             vreg_to_preg[instr[2]])

    return bundles


# ================================================================
# CLI Interface
# ================================================================

if __name__ == "__main__":
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

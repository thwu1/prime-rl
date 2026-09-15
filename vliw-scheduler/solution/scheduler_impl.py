"""
VLIW Instruction Scheduler with Register Allocation

Implements:
1. Dependency analysis (RAW, WAR, WAW hazards + memory ordering)
2. Critical-path priority computation
3. List scheduling into VLIW bundles
4. Liveness-based register allocation via greedy graph coloring
"""


import sys
sys.path.insert(0, "/app")
from isa import get_reads_writes, get_unit, is_memory_access


def _build_dependency_graph(instrs):
    """Build a dependency DAG over instruction indices.

    Tracks RAW (read-after-write), WAR (write-after-read), and WAW
    (write-after-write) register hazards, plus memory ordering constraints.

    Returns:
        deps: list of sets, where deps[i] is the set of instruction indices
              that instruction i depends on (must be scheduled before i).
    """
    n = len(instrs)
    deps = [set() for _ in range(n)]

    last_writer = {}          # reg -> index of last instruction that wrote it
    last_readers = {}         # reg -> set of indices that read it since last write
    last_mem_op = -1          # index of last memory access (load-from-mem or store)

    for i, instr in enumerate(instrs):
        reads, writes = get_reads_writes(instr)
        unit, op = instr[0], instr[1]

        # RAW: we read a register → depend on its last writer
        for r in reads:
            if r in last_writer:
                deps[i].add(last_writer[r])

        # WAW: we write a register → depend on its last writer
        for r in writes:
            if r in last_writer:
                deps[i].add(last_writer[r])

        # WAR: we write a register → depend on all readers since last write
        for r in writes:
            if r in last_readers:
                deps[i].update(last_readers[r])

        # Memory ordering: real memory accesses (load-from-mem, store)
        # must be kept in program order relative to each other.
        if is_memory_access(instr):
            if last_mem_op >= 0:
                deps[i].add(last_mem_op)
            last_mem_op = i

        # halt depends on all previous stores
        if unit == "flow" and op == "halt":
            for j in range(i):
                if instrs[j][0] == "store":
                    deps[i].add(j)

        # Update tracking structures
        for r in writes:
            last_writer[r] = i
            last_readers[r] = set()
        for r in reads:
            if r not in last_readers:
                last_readers[r] = set()
            last_readers[r].add(i)

    return deps


def _compute_priorities(instrs, deps):
    """Compute scheduling priority = longest path to any sink node.

    Higher priority means the instruction is on a longer critical path
    and should be scheduled earlier.
    """
    n = len(instrs)

    # Build successor graph
    succs = [set() for _ in range(n)]
    for i, d in enumerate(deps):
        for j in d:
            succs[j].add(i)

    # Topological order via iterative DFS
    visited = [False] * n
    topo_order = []

    for start in range(n):
        if visited[start]:
            continue
        stack = [(start, False)]
        while stack:
            node, processed = stack.pop()
            if visited[node]:
                continue
            if processed:
                visited[node] = True
                topo_order.append(node)
            else:
                stack.append((node, True))
                for s in succs[node]:
                    if not visited[s]:
                        stack.append((s, False))

    # Compute longest path from each node (process in topo order = leaves first)
    priority = [1] * n
    for node in topo_order:
        for s in succs[node]:
            priority[node] = max(priority[node], priority[s] + 1)

    return priority


def _list_schedule(instrs, deps, priorities):
    """Schedule instructions into VLIW bundles using list scheduling.

    At each cycle, the highest-priority ready instructions are assigned to
    available functional units, one instruction per unit.

    Returns a list of bundles (each bundle is a list of instruction indices).
    """
    n = len(instrs)

    # Build successor graph
    succs = [set() for _ in range(n)]
    for i, d in enumerate(deps):
        for j in d:
            succs[j].add(i)

    # In-degree for dependency tracking
    in_degree = [len(d) for d in deps]

    # Ready set: instructions with all dependencies met
    ready = set()
    for i in range(n):
        if in_degree[i] == 0:
            ready.add(i)

    bundles = []
    scheduled = set()

    while len(scheduled) < n:
        # Sort candidates by priority (highest first), break ties by index
        candidates = sorted(ready, key=lambda i: (-priorities[i], i))

        bundle = []
        used_units = set()
        scheduled_this_cycle = []

        for i in candidates:
            fu = get_unit(instrs[i])
            if fu not in used_units:
                bundle.append(i)
                used_units.add(fu)
                scheduled_this_cycle.append(i)

        assert scheduled_this_cycle, "Scheduling deadlock: no instructions could be scheduled"

        bundles.append(bundle)

        # Update ready set
        for i in scheduled_this_cycle:
            scheduled.add(i)
            ready.discard(i)
            for s in succs[i]:
                in_degree[s] -= 1
                if in_degree[s] == 0:
                    ready.add(s)

    return bundles


def _allocate_registers(instrs, bundle_indices, max_registers):
    """Allocate physical registers for a VLIW-scheduled program.

    Performs backward liveness analysis on bundles, builds an interference
    graph, and applies greedy coloring.

    Args:
        instrs: original instruction list (for reading register info)
        bundle_indices: list of bundles, each a list of instruction indices
        max_registers: maximum number of physical registers

    Returns:
        vreg_to_preg: dict mapping virtual register -> physical register
    """
    # Collect all virtual registers
    all_vregs = set()
    for b_indices in bundle_indices:
        for idx in b_indices:
            reads, writes = get_reads_writes(instrs[idx])
            all_vregs.update(reads)
            all_vregs.update(writes)

    # If all virtual regs are already in range, use identity mapping
    if not all_vregs or max(all_vregs) < max_registers:
        return {v: v for v in all_vregs}

    n_bundles = len(bundle_indices)

    # Compute gen/kill sets for each bundle
    gen_sets = []
    kill_sets = []
    for b_indices in bundle_indices:
        gen_b = set()
        kill_b = set()
        for idx in b_indices:
            reads, writes = get_reads_writes(instrs[idx])
            # Registers read before being written in this bundle
            gen_b.update(reads - kill_b)
            kill_b.update(writes)
        gen_sets.append(gen_b)
        kill_sets.append(kill_b)

    # Backward liveness analysis (fixed-point iteration)
    live_in = [set() for _ in range(n_bundles)]
    live_out = [set() for _ in range(n_bundles)]

    changed = True
    while changed:
        changed = False
        for i in range(n_bundles - 1, -1, -1):
            new_live_out = live_in[i + 1] if i + 1 < n_bundles else set()
            new_live_in = gen_sets[i] | (new_live_out - kill_sets[i])

            if new_live_in != live_in[i] or new_live_out != live_out[i]:
                live_in[i] = new_live_in
                live_out[i] = new_live_out
                changed = True

    # Build interference graph
    # Two vregs interfere if they are simultaneously live at any point
    interference = {v: set() for v in all_vregs}

    for i in range(n_bundles):
        # Registers live at this bundle = live_in ∪ kill (defs extend liveness)
        live_here = live_in[i] | kill_sets[i]

        for v1 in live_here:
            for v2 in live_here:
                if v1 != v2:
                    interference[v1].add(v2)
                    interference[v2].add(v1)

    # Greedy graph coloring (order by decreasing degree)
    vreg_to_preg = {}
    vregs_by_degree = sorted(all_vregs, key=lambda v: -len(interference[v]))

    for vreg in vregs_by_degree:
        used_colors = {vreg_to_preg[n] for n in interference[vreg]
                       if n in vreg_to_preg}
        for color in range(max_registers):
            if color not in used_colors:
                vreg_to_preg[vreg] = color
                break
        else:
            raise RuntimeError(
                f"Cannot allocate: need more than {max_registers} registers "
                f"(vreg {vreg} has {len(used_colors)} interfering neighbors)"
            )

    return vreg_to_preg


def _remap_instruction(instr, vreg_to_preg):
    """Rewrite an instruction's register operands using the allocation map."""
    unit, op = instr[0], instr[1]
    args = instr[2:]

    if unit == "alu":
        dst, src1, src2 = args
        return [unit, op, vreg_to_preg[dst], vreg_to_preg[src1],
                vreg_to_preg[src2]]
    elif unit == "load":
        if op == "const":
            return [unit, op, vreg_to_preg[args[0]], args[1]]
        else:  # "load"
            return [unit, op, vreg_to_preg[args[0]], vreg_to_preg[args[1]]]
    elif unit == "store":
        return [unit, op, vreg_to_preg[args[0]], vreg_to_preg[args[1]]]
    elif unit == "flow":
        if op == "mov":
            return [unit, op, vreg_to_preg[args[0]], vreg_to_preg[args[1]]]
        else:  # halt
            return list(instr)
    return list(instr)


def schedule(instructions, max_registers=256):
    """Schedule a sequential instruction list into VLIW bundles.

    Args:
        instructions: List of instructions, each [unit, op, ...args].
        max_registers: Maximum number of physical registers (default 256).

    Returns:
        List of bundles. Each bundle is a list of instructions that execute
        in one VLIW cycle.
    """
    # 1. Build dependency graph
    deps = _build_dependency_graph(instructions)

    # 2. Compute scheduling priorities (critical path length)
    priorities = _compute_priorities(instructions, deps)

    # 3. List scheduling into VLIW bundles
    bundle_indices = _list_schedule(instructions, deps, priorities)

    # 4. Register allocation
    vreg_to_preg = _allocate_registers(instructions, bundle_indices, max_registers)

    # 5. Build final bundles with physical registers
    bundles = []
    for b_indices in bundle_indices:
        bundle = [_remap_instruction(instructions[idx], vreg_to_preg)
                  for idx in b_indices]
        bundles.append(bundle)

    return bundles

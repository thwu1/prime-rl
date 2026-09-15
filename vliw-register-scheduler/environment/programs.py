"""Test programs for the VLIW optimizer.

Each program is a dict with:
    - name: human-readable name
    - instructions: list of instruction dicts (sequential, using virtual registers)
    - initial_memory: dict mapping address -> uint32 value
    - max_regs: maximum number of physical registers the optimizer may use
    - max_cycles: maximum number of VLIW bundles (cycles) allowed
"""



def _make_hash_instrs(input_vreg, start_vreg):
    """Generate myhash instructions (6-round integer hash).

    Based on a well-known integer hash function using add/xor/shift rounds.

    Args:
        input_vreg: virtual register containing the input value
        start_vreg: first available virtual register number

    Returns:
        (instructions, result_vreg, next_available_vreg)
    """
    instrs = []
    v = start_vreg
    a = input_vreg

    rounds = [
        (0x7ED55D16, 12, "add", "shl", "add"),   # round 1
        (0xC761C23C, 19, "xor", "shr", "xor"),   # round 2
        (0x165667B1, 5,  "add", "shl", "add"),    # round 3
        (0xD3A2646C, 9,  "add", "shl", "xor"),    # round 4
        (0xFD7046C5, 3,  "add", "shl", "add"),    # round 5
        (0xB55A4F09, 16, "xor", "shr", "xor"),    # round 6
    ]

    for magic, shift, op1, shift_op, op2 in rounds:
        magic_r = v; v += 1
        instrs.append({"op": "const", "dst": magic_r, "srcs": [], "imm": magic})
        shift_r = v; v += 1
        instrs.append({"op": "const", "dst": shift_r, "srcs": [], "imm": shift})
        t1 = v; v += 1
        instrs.append({"op": op1, "dst": t1, "srcs": [a, magic_r]})
        t2 = v; v += 1
        instrs.append({"op": shift_op, "dst": t2, "srcs": [a, shift_r]})
        a = v; v += 1
        instrs.append({"op": op2, "dst": a, "srcs": [t1, t2]})

    return instrs, a, v


def _make_single_hash():
    """Single myhash computation: load from mem[0], hash, store to mem[1]."""
    instrs = []
    v = 0

    addr_r = v; v += 1
    instrs.append({"op": "const", "dst": addr_r, "srcs": [], "imm": 0})
    input_r = v; v += 1
    instrs.append({"op": "load", "dst": input_r, "srcs": [addr_r]})

    hash_instrs, result_r, v = _make_hash_instrs(input_r, v)
    instrs.extend(hash_instrs)

    out_addr = v; v += 1
    instrs.append({"op": "const", "dst": out_addr, "srcs": [], "imm": 1})
    instrs.append({"op": "store", "dst": -1, "srcs": [out_addr, result_r]})
    instrs.append({"op": "halt", "dst": -1, "srcs": []})

    return {
        "name": "single_hash",
        "instructions": instrs,
        "initial_memory": {0: 0xDEADBEEF},
        "max_regs": 8,
        "max_cycles": 23,
    }


def _make_triple_hash():
    """Three independent myhash computations, XOR combined.

    Loads from mem[0], mem[1], mem[2]. Stores result to mem[10].
    High ILP potential: three independent hash chains can be interleaved.
    """
    instrs = []
    v = 0

    inputs = []
    for addr in [0, 1, 2]:
        addr_r = v; v += 1
        instrs.append({"op": "const", "dst": addr_r, "srcs": [], "imm": addr})
        input_r = v; v += 1
        instrs.append({"op": "load", "dst": input_r, "srcs": [addr_r]})
        inputs.append(input_r)

    results = []
    for inp in inputs:
        hash_instrs, result_r, v = _make_hash_instrs(inp, v)
        instrs.extend(hash_instrs)
        results.append(result_r)

    combined = results[0]
    for r in results[1:]:
        t = v; v += 1
        instrs.append({"op": "xor", "dst": t, "srcs": [combined, r]})
        combined = t

    out_addr = v; v += 1
    instrs.append({"op": "const", "dst": out_addr, "srcs": [], "imm": 10})
    instrs.append({"op": "store", "dst": -1, "srcs": [out_addr, combined]})
    instrs.append({"op": "halt", "dst": -1, "srcs": []})

    return {
        "name": "triple_hash",
        "instructions": instrs,
        "initial_memory": {0: 0xDEADBEEF, 1: 0xCAFEBABE, 2: 0x12345678},
        "max_regs": 14,
        "max_cycles": 55,
    }


def _make_pipeline_dag():
    """Diamond-shaped dependency DAG with mixed operations.

    Loads 4 values, computes pairwise operations (fan-out), combines results
    (fan-in), applies hash rounds, stores 2 outputs. Tests register pressure
    from overlapping lifetimes at convergence points.
    """
    instrs = [
        # Stage 1: Load 4 values from mem[0..3]
        {"op": "const", "dst": 0,  "srcs": [], "imm": 0},
        {"op": "load",  "dst": 1,  "srcs": [0]},
        {"op": "const", "dst": 2,  "srcs": [], "imm": 1},
        {"op": "load",  "dst": 3,  "srcs": [2]},
        {"op": "const", "dst": 4,  "srcs": [], "imm": 2},
        {"op": "load",  "dst": 5,  "srcs": [4]},
        {"op": "const", "dst": 6,  "srcs": [], "imm": 3},
        {"op": "load",  "dst": 7,  "srcs": [6]},

        # Stage 2: Pairwise ops (fan-out: each input used 2-3 times)
        {"op": "add",   "dst": 8,  "srcs": [1, 3]},    # a + b
        {"op": "xor",   "dst": 9,  "srcs": [1, 5]},    # a ^ c
        {"op": "add",   "dst": 10, "srcs": [3, 7]},     # b + d
        {"op": "xor",   "dst": 11, "srcs": [5, 7]},     # c ^ d
        {"op": "mul",   "dst": 12, "srcs": [1, 7]},     # a * d
        {"op": "mul",   "dst": 13, "srcs": [3, 5]},     # b * c

        # Stage 3: Second level combinations (fan-in + cross-references)
        {"op": "add",   "dst": 14, "srcs": [8, 10]},    # (a+b) + (b+d)
        {"op": "xor",   "dst": 15, "srcs": [9, 11]},    # (a^c) ^ (c^d)
        {"op": "add",   "dst": 16, "srcs": [12, 13]},   # (a*d) + (b*c)
        {"op": "xor",   "dst": 17, "srcs": [8, 12]},    # (a+b) ^ (a*d)

        # Stage 4: Hash round on v14
        {"op": "const", "dst": 18, "srcs": [], "imm": 0x7ED55D16},
        {"op": "const", "dst": 19, "srcs": [], "imm": 12},
        {"op": "add",   "dst": 20, "srcs": [14, 18]},
        {"op": "shl",   "dst": 21, "srcs": [14, 19]},
        {"op": "add",   "dst": 22, "srcs": [20, 21]},

        # Stage 5: Hash round on v15
        {"op": "const", "dst": 23, "srcs": [], "imm": 0xC761C23C},
        {"op": "const", "dst": 24, "srcs": [], "imm": 7},
        {"op": "xor",   "dst": 25, "srcs": [15, 23]},
        {"op": "shr",   "dst": 26, "srcs": [15, 24]},
        {"op": "xor",   "dst": 27, "srcs": [25, 26]},

        # Stage 6: Combine all results
        {"op": "xor",   "dst": 28, "srcs": [22, 27]},
        {"op": "add",   "dst": 29, "srcs": [28, 16]},
        {"op": "xor",   "dst": 30, "srcs": [29, 17]},

        # Stage 7: Final hash round
        {"op": "const", "dst": 31, "srcs": [], "imm": 0x165667B1},
        {"op": "const", "dst": 32, "srcs": [], "imm": 5},
        {"op": "add",   "dst": 33, "srcs": [30, 31]},
        {"op": "shl",   "dst": 34, "srcs": [30, 32]},
        {"op": "add",   "dst": 35, "srcs": [33, 34]},

        # Stage 8: Store 2 results
        {"op": "const", "dst": 36, "srcs": [], "imm": 10},
        {"op": "store", "dst": -1, "srcs": [36, 35]},
        {"op": "const", "dst": 37, "srcs": [], "imm": 11},
        {"op": "store", "dst": -1, "srcs": [37, 16]},

        {"op": "halt",  "dst": -1, "srcs": []},
    ]

    return {
        "name": "pipeline_dag",
        "instructions": instrs,
        "initial_memory": {
            0: 0x11111111, 1: 0x22222222,
            2: 0x33333333, 3: 0x44444444
        },
        "max_regs": 14,
        "max_cycles": 26,
    }


PROGRAMS = [
    _make_single_hash(),
    _make_triple_hash(),
    _make_pipeline_dag(),
]

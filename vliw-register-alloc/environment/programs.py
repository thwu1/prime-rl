"""
Test programs for the VLIW backend compiler.


Each test case returns (name, Program, max_regs, target_cycles).
"""

from vliw import Inst, Program, MASK32


def _prog_smoke():
    """
    Smoke test: load 4 values, compute sum/product/xor, store 3 results.
    15 instructions, 12 virtual registers.
    """
    insts = [
        Inst("li", 0, []),               # v0 = 0
        Inst("lw", 1, [0], 0),           # v1 = mem[0]
        Inst("lw", 2, [0], 1),           # v2 = mem[1]
        Inst("lw", 3, [0], 2),           # v3 = mem[2]
        Inst("lw", 4, [0], 3),           # v4 = mem[3]
        Inst("add", 5, [1, 2]),          # v5 = v1+v2
        Inst("add", 6, [3, 4]),          # v6 = v3+v4
        Inst("add", 7, [5, 6]),          # v7 = sum
        Inst("mul", 8, [1, 2]),          # v8 = v1*v2
        Inst("mul", 9, [3, 4]),          # v9 = v3*v4
        Inst("mul", 10, [8, 9]),         # v10 = product
        Inst("xor", 11, [7, 10]),        # v11 = sum^product
        Inst("sw", -1, [0, 7], 4),       # mem[4] = sum
        Inst("sw", -1, [0, 10], 5),      # mem[5] = product
        Inst("sw", -1, [0, 11], 6),      # mem[6] = xor
    ]
    init_mem = [100, 200, 300, 400] + [0] * 252
    return "smoke", Program(insts, 12, 8, init_mem), 32, 25


def _prog_scheduling():
    """
    Two independent hash chains that benefit from VLIW interleaving.
    28 instructions, 24 virtual registers.
    """
    insts = [
        # Load inputs
        Inst("li", 0, []),                 # v0 = 0
        Inst("lw", 1, [0], 0),             # v1 chain-A input
        Inst("lw", 2, [0], 1),             # v2 chain-A input
        Inst("lw", 3, [0], 2),             # v3 chain-B input
        Inst("lw", 4, [0], 3),             # v4 chain-B input

        # Chain A (v1,v2 → v12)
        Inst("add", 5, [1, 2]),            # v5
        Inst("xor", 6, [5, 1]),            # v6
        Inst("shl", 7, [6, 2]),            # v7
        Inst("add", 8, [7, 5]),            # v8
        Inst("xor", 9, [8, 6]),            # v9
        Inst("mul", 10, [9, 5]),           # v10 (MUL, 3-cycle lat)
        Inst("add", 11, [10, 8]),          # v11
        Inst("xor", 12, [11, 9]),          # v12

        # Chain B (v3,v4 → v20)   -- independent of chain A
        Inst("add", 13, [3, 4]),           # v13
        Inst("xor", 14, [13, 3]),          # v14
        Inst("shl", 15, [14, 4]),          # v15
        Inst("add", 16, [15, 13]),         # v16
        Inst("xor", 17, [16, 14]),         # v17
        Inst("mul", 18, [17, 13]),         # v18 (MUL)
        Inst("add", 19, [18, 16]),         # v19
        Inst("xor", 20, [19, 17]),         # v20

        # Combine
        Inst("xor", 21, [12, 20]),         # v21
        Inst("mul", 22, [12, 20]),         # v22 (MUL)
        Inst("add", 23, [21, 22]),         # v23

        # Store
        Inst("sw", -1, [0, 12], 4),        # mem[4] = chain A
        Inst("sw", -1, [0, 20], 5),        # mem[5] = chain B
        Inst("sw", -1, [0, 23], 6),        # mem[6] = combined
    ]
    init_mem = [0x12345678, 0x9ABCDEF0, 0xDEADBEEF, 0xCAFEBABE] + [0] * 252
    return "scheduling", Program(insts, 24, 8, init_mem), 32, 40


def _prog_pressure():
    """
    High register pressure: load 12 values, compute pairwise, combine with
    originals.  ~55 instructions, ~42 virtual registers, max_regs=16.
    Forces register spilling.
    """
    insts = []
    v = 0

    # v0 = base address
    insts.append(Inst("li", v, [])); base = v; v += 1

    # Load 12 values (v1..v12)
    loads = []
    for i in range(12):
        insts.append(Inst("lw", v, [base], i))
        loads.append(v)
        v += 1

    # Pairwise ops on consecutive pairs (6 groups of 2) -- all 12 loads alive
    pair_results = []
    for i in range(0, 12, 2):
        a, b = loads[i], loads[i + 1]
        insts.append(Inst("add", v, [a, b])); t1 = v; v += 1
        insts.append(Inst("mul", v, [a, b])); t2 = v; v += 1
        insts.append(Inst("xor", v, [t1, t2])); t3 = v; v += 1
        pair_results.append(t3)

    # Chain-reduce pairwise results
    cur = pair_results[0]
    for r in pair_results[1:]:
        insts.append(Inst("add", v, [cur, r])); cur = v; v += 1

    # XOR with the first 6 original loads (keeps them alive across computation)
    for lr in loads[:6]:
        insts.append(Inst("xor", v, [cur, lr])); cur = v; v += 1

    # Store 3 results
    insts.append(Inst("sw", -1, [base, cur], 16))
    # Also store an intermediate for extra verification
    insts.append(Inst("sw", -1, [base, pair_results[0]], 17))
    insts.append(Inst("sw", -1, [base, pair_results[-1]], 18))

    init_mem = [(i * 0x01010101 + 0x13) & MASK32 for i in range(20)] + [0] * 236
    return "pressure", Program(insts, v, 20, init_mem), 16, 120


def _prog_mixed():
    """
    Mixed workload: matrix-vector multiply (4x4) plus hash post-processing.
    Tests MUL scheduling, memory traffic, and moderate register pressure.
    ~60 instructions, ~50 virtual registers, max_regs=20.
    """
    insts = []
    v = 0

    # v0 = base address
    insts.append(Inst("li", v, [])); base = v; v += 1

    # Load 4x4 matrix A from mem[0..15]
    a = []
    for i in range(16):
        insts.append(Inst("lw", v, [base], i)); a.append(v); v += 1

    # Load vector x from mem[16..19]
    x = []
    for i in range(4):
        insts.append(Inst("lw", v, [base], 16 + i)); x.append(v); v += 1

    # y[i] = sum_j A[i][j] * x[j]   (4 dot products)
    y = []
    for i in range(4):
        # First multiply
        insts.append(Inst("mul", v, [a[i*4], x[0]])); acc = v; v += 1
        for j in range(1, 4):
            insts.append(Inst("mul", v, [a[i*4+j], x[j]])); tmp = v; v += 1
            insts.append(Inst("add", v, [acc, tmp])); acc = v; v += 1
        y.append(acc)

    # Hash post-processing: chain the y values
    cur = y[0]
    for yv in y[1:]:
        insts.append(Inst("xor", v, [cur, yv])); cur = v; v += 1
        insts.append(Inst("shl", v, [cur, y[0]])); cur = v; v += 1

    # Store results
    for i, yv in enumerate(y):
        insts.append(Inst("sw", -1, [base, yv], 20 + i))
    insts.append(Inst("sw", -1, [base, cur], 24))

    init_mem = [(i * 7 + 3) & MASK32 for i in range(24)] + [0] * 232
    return "mixed", Program(insts, v, 28, init_mem), 20, 100


def get_test_cases():
    """Return list of (name, Program, max_regs, target_cycles)."""
    return [
        _prog_smoke(),
        _prog_scheduling(),
        _prog_pressure(),
        _prog_mixed(),
    ]

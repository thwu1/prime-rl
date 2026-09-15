"""
Test programs for the VLIW optimizer.

Each program is an SSA program using virtual register names (strings).
The optimizer must map these to physical registers and schedule into
VLIW bundles.

All inputs come from memory (via MOVI + LOAD).
All outputs go to memory (via MOVI + STORE).
Correctness is verified by comparing final memory state.
"""

MASK32 = 0xFFFFFFFF


def _make_poly_batch():
    """Evaluate f(x) = 3x^2 + 7x + 11 on 4 array elements."""
    instrs = [
        ("MOVI", "ca", 3), ("MOVI", "cb", 7),
        ("MOVI", "cc", 11), ("MOVI", "obase", 100),
    ]
    for i in range(4):
        p = str(i)
        instrs += [
            ("MOVI", f"ai{p}", i),
            ("LOAD", f"x{p}", f"ai{p}"),
            ("MUL", f"x2{p}", f"x{p}", f"x{p}"),
            ("MUL", f"ax{p}", "ca", f"x2{p}"),
            ("MUL", f"bx{p}", "cb", f"x{p}"),
            ("ADD", f"s{p}", f"ax{p}", f"bx{p}"),
            ("ADD", f"r{p}", f"s{p}", "cc"),
            ("MOVI", f"oi{p}", i),
            ("ADD", f"oa{p}", "obase", f"oi{p}"),
            ("STORE", f"oa{p}", f"r{p}"),
        ]
    return instrs


def _make_tree_walk():
    """Walk a binary tree, hashing node values at each step."""
    instrs = [
        ("MOVI", "hc", 0xDEADBEEF), ("MOVI", "sh", 7),
        ("MOVI", "one", 1), ("MOVI", "zero", 0),
        ("LOAD", "val0", "zero"), ("MOVI", "ri", 1),
        ("LOAD", "nd0", "ri"),
    ]
    pv, pn, pi = "val0", "nd0", "ri"
    for r in range(4):
        p = str(r)
        instrs += [
            ("XOR", f"xv{p}", pv, pn),
            ("ADD", f"h1{p}", f"xv{p}", "hc"),
            ("SHR", f"h2{p}", f"xv{p}", "sh"),
            ("XOR", f"vl{p}", f"h1{p}", f"h2{p}"),
            ("AND", f"bt{p}", f"vl{p}", "one"),
            ("SHL", f"i2{p}", pi, "one"),
            ("ADD", f"i3{p}", f"i2{p}", "one"),
            ("ADD", f"ni{p}", f"i3{p}", f"bt{p}"),
        ]
        if r < 3:
            instrs.append(("LOAD", f"nn{p}", f"ni{p}"))
            pn = f"nn{p}"
        pv, pi = f"vl{p}", f"ni{p}"
    instrs += [("MOVI", "oa", 200), ("STORE", "oa", "vl3")]
    return instrs


def _make_matmul():
    """2x2 matrix multiply: C = A * B."""
    instrs = []
    # Load A from mem[0..3] (row-major: A[0][0], A[0][1], A[1][0], A[1][1])
    for i in range(4):
        instrs += [("MOVI", f"aa{i}", i), ("LOAD", f"a{i}", f"aa{i}")]
    # Load B from mem[4..7]
    for i in range(4):
        instrs += [("MOVI", f"ba{i}", 4 + i), ("LOAD", f"b{i}", f"ba{i}")]
    # C[0][0] = A[0][0]*B[0][0] + A[0][1]*B[1][0]
    instrs += [("MUL", "m00", "a0", "b0"), ("MUL", "m01", "a1", "b2"),
               ("ADD", "c00", "m00", "m01")]
    # C[0][1] = A[0][0]*B[0][1] + A[0][1]*B[1][1]
    instrs += [("MUL", "m10", "a0", "b1"), ("MUL", "m11", "a1", "b3"),
               ("ADD", "c01", "m10", "m11")]
    # C[1][0] = A[1][0]*B[0][0] + A[1][1]*B[1][0]
    instrs += [("MUL", "m20", "a2", "b0"), ("MUL", "m21", "a3", "b2"),
               ("ADD", "c10", "m20", "m21")]
    # C[1][1] = A[1][0]*B[0][1] + A[1][1]*B[1][1]
    instrs += [("MUL", "m30", "a2", "b1"), ("MUL", "m31", "a3", "b3"),
               ("ADD", "c11", "m30", "m31")]
    # Store C to mem[100..103]
    for i, n in enumerate(["c00", "c01", "c10", "c11"]):
        instrs += [("MOVI", f"ca{i}", 100 + i), ("STORE", f"ca{i}", n)]
    return instrs


# Build deterministic tree memory for tree_walk program
_tree_init_mem = {0: 0xCAFEBABE}
for _i in range(1, 64):
    _tree_init_mem[_i] = (_i * 0x9E3779B9 + 0x12345678) & MASK32


PROGRAMS = [
    {
        "name": "basic_arith",
        "num_regs": 24,
        "initial_mem": {0: 42, 1: 17},
        "check_addrs": [100, 101, 102],
        "target_cycles": 18,
        "instructions": [
            ("MOVI", "a0", 0), ("MOVI", "a1", 1),
            ("LOAD", "x", "a0"), ("LOAD", "y", "a1"),
            ("ADD", "sum", "x", "y"),
            ("MUL", "prod", "x", "y"),
            ("SUB", "diff", "x", "y"),
            ("MOVI", "o0", 100), ("MOVI", "o1", 101), ("MOVI", "o2", 102),
            ("STORE", "o0", "sum"),
            ("STORE", "o1", "prod"),
            ("STORE", "o2", "diff"),
        ],
    },
    {
        "name": "hash_compute",
        "num_regs": 24,
        "initial_mem": {0: 0x42},
        "check_addrs": [100],
        "target_cycles": 35,
        "instructions": [
            ("MOVI", "addr", 0), ("LOAD", "a", "addr"),
            # Round 1: a = (a + 0x7ED55D16) + (a << 12)
            ("MOVI", "c1", 0x7ED55D16), ("MOVI", "s1", 12),
            ("SHL", "t1", "a", "s1"), ("ADD", "t2", "a", "c1"),
            ("ADD", "a1", "t2", "t1"),
            # Round 2: a = (a ^ 0xC761C23C) ^ (a >> 19)
            ("MOVI", "c2", 0xC761C23C), ("MOVI", "s2", 19),
            ("SHR", "t3", "a1", "s2"), ("XOR", "t4", "a1", "c2"),
            ("XOR", "a2", "t4", "t3"),
            # Round 3: a = (a + 0x165667B1) + (a << 5)
            ("MOVI", "c3", 0x165667B1), ("MOVI", "s3", 5),
            ("SHL", "t5", "a2", "s3"), ("ADD", "t6", "a2", "c3"),
            ("ADD", "a3", "t6", "t5"),
            # Round 4: a = (a + 0xD3A2646C) ^ (a << 9)
            ("MOVI", "c4", 0xD3A2646C), ("MOVI", "s4", 9),
            ("SHL", "t7", "a3", "s4"), ("ADD", "t8", "a3", "c4"),
            ("XOR", "a4", "t8", "t7"),
            # Round 5: a = (a + 0xFD7046C5) + (a << 3)
            ("MOVI", "c5", 0xFD7046C5), ("MOVI", "s5", 3),
            ("SHL", "t9", "a4", "s5"), ("ADD", "t10", "a4", "c5"),
            ("ADD", "a5", "t10", "t9"),
            # Round 6: a = (a ^ 0xB55A4F09) ^ (a >> 16)
            ("MOVI", "c6", 0xB55A4F09), ("MOVI", "s6", 16),
            ("SHR", "t11", "a5", "s6"), ("XOR", "t12", "a5", "c6"),
            ("XOR", "a6", "t12", "t11"),
            # Store result
            ("MOVI", "out", 100), ("STORE", "out", "a6"),
        ],
    },
    {
        "name": "poly_batch",
        "num_regs": 24,
        "initial_mem": {0: 2, 1: 5, 2: 8, 3: 11},
        "check_addrs": [100, 101, 102, 103],
        "target_cycles": 55,
        "instructions": _make_poly_batch(),
    },
    {
        "name": "tree_walk",
        "num_regs": 24,
        "initial_mem": _tree_init_mem,
        "check_addrs": [200],
        "target_cycles": 60,
        "instructions": _make_tree_walk(),
    },
    {
        "name": "matmul_2x2",
        "num_regs": 24,
        "initial_mem": {0: 3, 1: 7, 2: 11, 3: 13, 4: 2, 5: 5, 6: 8, 7: 3},
        "check_addrs": [100, 101, 102, 103],
        "target_cycles": 35,
        "instructions": _make_matmul(),
    },
]

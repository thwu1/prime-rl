#!/usr/bin/env python3
"""
Generate benchmark programs for the VLIW scheduler task.

Programs are based on the myhash function from tinygrad's anthropic_challenge.py,
which uses bitwise operations typical of tree-hashing computations.

Each program is saved as a JSON file containing:
  - name: human-readable identifier
  - instructions: sequential instruction list
  - memory_init: initial memory state
  - expected_memory: correct memory state after execution
"""


import json
import os
import sys

MASK32 = 0xFFFFFFFF


def _exec_alu(op, v1, v2):
    if op == "add": return (v1 + v2) & MASK32
    elif op == "sub": return (v1 - v2) & MASK32
    elif op == "mul": return (v1 * v2) & MASK32
    elif op == "shr": return (v1 >> (v2 & 31)) & MASK32
    elif op == "shl": return (v1 << (v2 & 31)) & MASK32
    elif op == "xor": return v1 ^ v2
    elif op == "and": return v1 & v2
    elif op == "or":  return v1 | v2
    elif op == "cmplt": return 1 if v1 < v2 else 0
    elif op == "mod": return (v1 % v2) & MASK32 if v2 != 0 else 0
    raise ValueError(f"Unknown op: {op}")


def simulate_sequential(instrs, memory_init):
    """Simulate a sequential program and return final memory state."""
    regs = {}
    memory = dict(memory_init)
    for instr in instrs:
        unit, op = instr[0], instr[1]
        args = instr[2:]
        if unit == "alu":
            dst, src1, src2 = args
            regs[dst] = _exec_alu(op, regs.get(src1, 0), regs.get(src2, 0))
        elif unit == "load":
            if op == "const":
                regs[args[0]] = args[1] & MASK32
            else:
                regs[args[0]] = memory.get(regs.get(args[1], 0), 0)
        elif unit == "store":
            memory[regs.get(args[0], 0)] = regs.get(args[1], 0)
        elif unit == "flow":
            if op == "halt":
                break
            elif op == "mov":
                regs[args[0]] = regs.get(args[1], 0)
    return memory


def myhash_instrs(input_reg, temp_base):
    """Generate instructions for one complete myhash computation.

    Based on the hash function from tinygrad's anthropic_challenge.py:
        a = (a + 0x7ED55D16) + (a << 12)
        a = (a ^ 0xC761C23C) ^ (a >> 19)
        a = (a + 0x165667B1) + (a << 5)
        a = (a + 0xD3A2646C) ^ (a << 9)
        a = (a + 0xFD7046C5) + (a << 3)
        a = (a ^ 0xB55A4F09) ^ (a >> 16)

    Returns: (instruction_list, output_register)
    Uses temp registers [temp_base, temp_base + 29].
    """
    instrs = []
    t = temp_base
    a = input_reg

    rounds = [
        (0x7ED55D16, "add", 12, "shl", "add"),
        (0xC761C23C, "xor", 19, "shr", "xor"),
        (0x165667B1, "add",  5, "shl", "add"),
        (0xD3A2646C, "add",  9, "shl", "xor"),
        (0xFD7046C5, "add",  3, "shl", "add"),
        (0xB55A4F09, "xor", 16, "shr", "xor"),
    ]

    for magic, op1, shift, shift_op, op2 in rounds:
        instrs.append(["load", "const", t, magic])
        instrs.append(["alu", op1, t + 1, a, t])
        instrs.append(["load", "const", t + 2, shift])
        instrs.append(["alu", shift_op, t + 3, a, t + 2])
        instrs.append(["alu", op2, t + 4, t + 1, t + 3])
        a = t + 4
        t += 5

    return instrs, a


# ---------------------------------------------------------------------------
# Program 1: Simple arithmetic (19 instructions)
#   Two independent computation chains that merge, then store results.
#   All virtual registers < 256, so register allocation is trivial.
# ---------------------------------------------------------------------------
def generate_prog1():
    instrs = [
        ["load", "const", 0, 42],        # r0 = 42
        ["load", "const", 1, 17],        # r1 = 17
        ["alu",  "add",   2, 0, 1],      # r2 = 59
        ["load", "const", 3, 3],         # r3 = 3
        ["alu",  "mul",   4, 2, 3],      # r4 = 177
        ["load", "const", 5, 2],         # r5 = 2
        ["alu",  "shl",   6, 4, 5],      # r6 = 708
        ["load", "const", 7, 100],       # r7 = 100
        ["load", "const", 8, 7],         # r8 = 7
        ["alu",  "sub",   9, 7, 8],      # r9 = 93
        ["alu",  "xor",  10, 9, 7],      # r10 = 93^100 = 57
        ["alu",  "and",  11, 10, 8],     # r11 = 57&7 = 1
        ["alu",  "add",  12, 6, 11],     # r12 = 709
        ["alu",  "or",   13, 12, 0],     # r13 = 709|42 = 735
        ["load", "const", 14, 0],        # r14 = 0 (address)
        ["store","store", 14, 13],       # mem[0] = 735
        ["load", "const", 15, 1],        # r15 = 1 (address)
        ["store","store", 15, 12],       # mem[1] = 709
        ["flow", "halt"],
    ]
    memory_init = {}
    expected = simulate_sequential(instrs, memory_init)
    return {"name": "simple_arithmetic", "instructions": instrs,
            "memory_init": memory_init, "expected_memory": expected}


# ---------------------------------------------------------------------------
# Program 2: Two independent hash chains (~72 instructions)
#   Loads two values from memory, computes myhash on each independently,
#   combines results, and stores. Virtual registers stay < 256.
# ---------------------------------------------------------------------------
def generate_prog2():
    instrs = []

    # Load two input values from memory
    instrs.append(["load", "const", 100, 0])    # r100 = address 0
    instrs.append(["load", "load",    0, 100])   # r0 = mem[0]
    instrs.append(["load", "const", 101, 1])     # r101 = address 1
    instrs.append(["load", "load",   50, 101])   # r50 = mem[1]

    # Hash chain 1: myhash(r0), temps in r10..r39, result in r39
    h1, h1_out = myhash_instrs(0, 10)
    instrs.extend(h1)

    # Hash chain 2: myhash(r50), temps in r60..r89, result in r89
    h2, h2_out = myhash_instrs(50, 60)
    instrs.extend(h2)

    # Combine
    instrs.append(["alu", "xor", 95, h1_out, h2_out])

    # Store results
    instrs.append(["load", "const", 96, 10])
    instrs.append(["store","store", 96, 95])         # mem[10] = combined
    instrs.append(["load", "const", 97, 11])
    instrs.append(["store","store", 97, h1_out])     # mem[11] = hash1
    instrs.append(["load", "const", 98, 12])
    instrs.append(["store","store", 98, h2_out])     # mem[12] = hash2
    instrs.append(["flow", "halt"])

    memory_init = {0: 0xDEADBEEF, 1: 0xCAFEBABE}
    expected = simulate_sequential(instrs, memory_init)
    return {"name": "hash_chain", "instructions": instrs,
            "memory_init": memory_init, "expected_memory": expected}


# ---------------------------------------------------------------------------
# Program 3: Four independent hash chains + final hash (~180 instructions)
#   Uses virtual registers > 255, so register allocation IS required.
#   Loads 4 values from memory, hashes each, combines pairwise,
#   applies a final hash to the combined result, stores everything.
# ---------------------------------------------------------------------------
def generate_prog3():
    instrs = []

    # Load four input values from memory addresses 0..3
    for i in range(4):
        instrs.append(["load", "const", 500 + i, i])
        instrs.append(["load", "load",  400 + i, 500 + i])

    # Four independent hash chains with high register numbers
    hash_results = []
    for i in range(4):
        h, h_out = myhash_instrs(400 + i, 1000 + i * 40)
        instrs.extend(h)
        hash_results.append(h_out)

    # Pairwise combination
    instrs.append(["alu", "xor", 2000, hash_results[0], hash_results[1]])
    instrs.append(["alu", "xor", 2001, hash_results[2], hash_results[3]])
    instrs.append(["alu", "xor", 2002, 2000, 2001])

    # Final hash of combined result
    h_final, h_final_out = myhash_instrs(2002, 3000)
    instrs.extend(h_final)

    # Store all results
    instrs.append(["load", "const", 3100, 100])
    instrs.append(["store","store", 3100, h_final_out])     # mem[100] = final_hash
    instrs.append(["load", "const", 3101, 101])
    instrs.append(["store","store", 3101, 2002])            # mem[101] = xor_combined
    for i in range(4):
        instrs.append(["load", "const", 3102 + i, 102 + i])
        instrs.append(["store","store", 3102 + i, hash_results[i]])  # mem[102+i]

    instrs.append(["flow", "halt"])

    memory_init = {0: 0xDEADBEEF, 1: 0xCAFEBABE, 2: 0x12345678, 3: 0xFEEDFACE}
    expected = simulate_sequential(instrs, memory_init)
    return {"name": "quad_hash", "instructions": instrs,
            "memory_init": memory_init, "expected_memory": expected}


def main():
    os.makedirs("/app/programs", exist_ok=True)
    generators = [generate_prog1, generate_prog2, generate_prog3]

    for i, gen in enumerate(generators, 1):
        prog = gen()
        # JSON requires string keys for dicts
        prog["memory_init"] = {str(k): v for k, v in prog["memory_init"].items()}
        prog["expected_memory"] = {str(k): v for k, v in prog["expected_memory"].items()}

        path = f"/app/programs/prog{i}.json"
        with open(path, "w") as f:
            json.dump(prog, f, indent=2)

        n_instrs = len(prog["instructions"])
        max_vreg = 0
        for instr in prog["instructions"]:
            for a in instr[2:]:
                if isinstance(a, int) and not (instr[0] == "load" and instr[1] == "const" and a == instr[3]):
                    max_vreg = max(max_vreg, a)
        print(f"prog{i} ({prog['name']}): {n_instrs} instructions, "
              f"max virtual reg ~{max_vreg}, "
              f"{len(prog['expected_memory'])} memory outputs")


if __name__ == "__main__":
    main()

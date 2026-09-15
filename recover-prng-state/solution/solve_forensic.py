
"""
Solution for PRNG forensic analysis and security evaluation task.

Strategy:
1. Disassemble all 3 binaries (done by solve.sh) to identify algorithms:
   - gen_alpha: MT19937 variant (constants 624, 397, 0x9908B0DF, custom tempering)
   - gen_beta: xorshift128 (shifts 11, 8, 19; 4-word state rotation)
   - gen_gamma: 64-bit LCG (multiplier 0x5851F42D4C957F2D, increment 0x14057B7EF767814F)

2. Match streams to generators by testing each algorithm against each stream:
   - xorshift128: state = last 4 outputs; verify by predicting from earlier outputs
   - LCG: brute-force lower 32 bits of state from 2 outputs, verify with 3rd
   - MT: GF(2) tempering matrix inversion on 624 outputs, verify on remaining

3. Predict next 5 outputs for each matched stream.

4. Assess weakest: xorshift128 (gen_beta) — state IS the output, trivially predictable.

5. Write quantitative vulnerability assessment ranking all three generators.
"""

import json
import struct
import subprocess
import os
import sys

# ========== xorshift128 ==========

MASK32 = 0xFFFFFFFF


def xs128_next(a, b, c, d):
    """One step of xorshift128. Returns (new_a, new_b, new_c, new_d, output)."""
    t = d
    s = a
    nd = c
    nc = b
    nb = a
    t = (t ^ ((t << 11) & MASK32)) & MASK32
    t = (t ^ (t >> 8)) & MASK32
    s = (s ^ (s >> 19)) & MASK32
    na = (t ^ s) & MASK32
    return na, nb, nc, nd, na


def check_xorshift128(vals):
    """Check if vals could be from xorshift128. Returns True if consistent."""
    if len(vals) < 10:
        return False
    for start in range(0, min(20, len(vals) - 4)):
        a, b, c, d = vals[start + 3], vals[start + 2], vals[start + 1], vals[start]
        na, nb, nc, nd, out = xs128_next(a, b, c, d)
        if start + 4 < len(vals) and out != vals[start + 4]:
            return False
    return True


def predict_xorshift128(vals, count):
    """Predict next outputs from xorshift128 stream."""
    n = len(vals)
    a = vals[n - 1]
    b = vals[n - 2]
    c = vals[n - 3]
    d = vals[n - 4]
    predictions = []
    for _ in range(count):
        a, b, c, d, out = xs128_next(a, b, c, d)
        predictions.append(out)
    return predictions


# ========== LCG64 ==========

LCG_MULT = 6364136223846793005
LCG_INC = 1442695040888963407
MASK64 = (1 << 64) - 1


def lcg_advance(state):
    return (state * LCG_MULT + LCG_INC) & MASK64


def check_lcg_and_recover(vals):
    """Try to recover LCG state from first 2 outputs using C brute-force.
    Returns recovered state_1 or None."""
    o0 = vals[0]
    o1 = vals[1]
    try:
        result = subprocess.run(
            ["/tmp/lcg_crack", f"{o0:08x}", f"{o1:08x}"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return None
        state_hex = result.stdout.strip()
        state_1 = int(state_hex, 16)

        # Verify with output[2]
        state_2 = lcg_advance(state_1)
        if (state_2 >> 32) & MASK32 != vals[1]:
            return None
        state_3 = lcg_advance(state_2)
        if (state_3 >> 32) & MASK32 != vals[2]:
            return None

        return state_1
    except Exception as e:
        print(f"  LCG crack failed: {e}")
        return None


def predict_lcg(state_1, total_observed, count):
    """Predict next outputs from LCG given state_1 and number already observed."""
    state = state_1
    # Advance past all observed outputs
    for _ in range(total_observed - 1):
        state = lcg_advance(state)
    # Now state corresponds to the last observed output
    # Generate predictions
    predictions = []
    for _ in range(count):
        state = lcg_advance(state)
        predictions.append((state >> 32) & MASK32)
    return predictions


# ========== Modified MT19937 ==========

N_MT = 624
M_MT = 397
MT_MATRIX_A = 0x9908B0DF
MT_UPPER_MASK = 0x80000000
MT_LOWER_MASK = 0x7FFFFFFF

TEMPER_U = 13
TEMPER_S = 9
TEMPER_B = 0xB5A7C4E0
TEMPER_T = 17
TEMPER_C = 0xD3E40000
TEMPER_L = 15


def temper(y):
    y ^= (y >> TEMPER_U)
    y ^= (y << TEMPER_S) & TEMPER_B
    y ^= (y << TEMPER_T) & TEMPER_C
    y ^= (y >> TEMPER_L)
    return y & MASK32


def build_temper_matrix():
    mat = [[0] * 32 for _ in range(32)]
    for i in range(32):
        t = temper(1 << (31 - i))
        for j in range(32):
            mat[j][i] = (t >> (31 - j)) & 1
    return mat


def gf2_matrix_inverse(mat):
    n = len(mat)
    aug = [row[:] + [1 if i == j else 0 for j in range(n)]
           for i, row in enumerate(mat)]
    for col in range(n):
        pivot = -1
        for row in range(col, n):
            if aug[row][col] == 1:
                pivot = row
                break
        if pivot == -1:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(n):
            if row != col and aug[row][col] == 1:
                for k in range(2 * n):
                    aug[row][k] ^= aug[col][k]
    return [row[n:] for row in aug]


def gf2_mat_vec_mul(mat, val):
    v = [(val >> (31 - i)) & 1 for i in range(32)]
    result = 0
    for i in range(32):
        bit = 0
        for j in range(32):
            bit ^= (mat[i][j] & v[j])
        result |= (bit << (31 - i))
    return result


def untemper(y, inv_matrix):
    return gf2_mat_vec_mul(inv_matrix, y)


def mt_twist(mt_state):
    mt = list(mt_state)
    for i in range(N_MT):
        y = (mt[i] & MT_UPPER_MASK) | (mt[(i + 1) % N_MT] & MT_LOWER_MASK)
        mt[i] = mt[(i + M_MT) % N_MT] ^ (y >> 1)
        if y & 1:
            mt[i] ^= MT_MATRIX_A
    return mt


def check_mt_and_recover(vals):
    """Try to recover MT state from first 624 outputs. Returns state tuple or None."""
    if len(vals) < N_MT + 5:
        return None

    T = build_temper_matrix()
    T_inv = gf2_matrix_inverse(T)
    if T_inv is None:
        return None

    # Recover internal state from first 624 outputs
    state = [untemper(vals[i], T_inv) for i in range(N_MT)]

    # Verify recovery
    for i in range(N_MT):
        if temper(state[i]) != vals[i]:
            return None

    # Apply twist
    twisted = mt_twist(state)

    # Verify against outputs 624+
    for i in range(min(10, len(vals) - N_MT)):
        if temper(twisted[i]) != vals[N_MT + i]:
            return None

    return (state, twisted)


def predict_mt(state, twisted, total_observed, count):
    """Predict next outputs from MT given recovered state."""
    idx = total_observed - N_MT

    mt = list(twisted)
    predictions = []
    while len(predictions) < count:
        if idx >= N_MT:
            mt = mt_twist(mt)
            idx = 0
        predictions.append(temper(mt[idx]))
        idx += 1

    return predictions[:count]


# ========== Main forensic analysis ==========


def read_stream(path):
    with open(path, "rb") as f:
        data = f.read()
    n = len(data) // 4
    return list(struct.unpack(f"<{n}I", data))


def main():
    streams = {}
    for i in range(1, 4):
        path = f"/app/stream_{i}.bin"
        streams[f"stream_{i}"] = read_stream(path)
        print(f"Read {len(streams[f'stream_{i}'])} values from {path}")

    matching = {}
    predictions = {}
    unmatched_streams = set(streams.keys())

    # --- Phase 1: Identify xorshift128 stream ---
    print("\n--- Phase 1: Testing for xorshift128 ---")
    for sname in sorted(unmatched_streams):
        vals = streams[sname]
        if check_xorshift128(vals):
            print(f"  {sname}: MATCH (xorshift128 recurrence verified)")
            matching[sname] = "gen_beta"
            predictions[sname] = predict_xorshift128(vals, 5)
            unmatched_streams.remove(sname)
            break
        else:
            print(f"  {sname}: no match")

    # --- Phase 2: Identify LCG stream ---
    print("\n--- Phase 2: Testing for LCG64 ---")
    for sname in sorted(unmatched_streams):
        vals = streams[sname]
        state_1 = check_lcg_and_recover(vals)
        if state_1 is not None:
            print(f"  {sname}: MATCH (LCG state recovered: 0x{state_1:016x})")
            matching[sname] = "gen_gamma"
            predictions[sname] = predict_lcg(state_1, len(vals), 5)
            unmatched_streams.remove(sname)
            break
        else:
            print(f"  {sname}: no match")

    # --- Phase 3: Remaining stream must be MT ---
    print("\n--- Phase 3: Testing for modified MT19937 ---")
    remaining = list(unmatched_streams)[0]
    vals = streams[remaining]
    result = check_mt_and_recover(vals)
    if result is not None:
        state, twisted = result
        print(f"  {remaining}: MATCH (MT state recovered and verified)")
        matching[remaining] = "gen_alpha"
        predictions[remaining] = predict_mt(state, twisted, len(vals), 5)
    else:
        print(f"  {remaining}: ERROR - MT recovery failed!")
        sys.exit(1)

    # --- Write results ---
    print("\n--- Writing results ---")

    # matching.txt
    with open("/app/matching.txt", "w") as f:
        for sname in ["stream_1", "stream_2", "stream_3"]:
            f.write(f"{sname}={matching[sname]}\n")
            print(f"  {sname} = {matching[sname]}")

    # predictions
    for sname in ["stream_1", "stream_2", "stream_3"]:
        num = sname.split("_")[1]
        path = f"/app/predictions_{num}.txt"
        with open(path, "w") as f:
            for val in predictions[sname]:
                f.write(f"0x{val:08x}\n")
        print(f"  Wrote {len(predictions[sname])} predictions to {path}")
        for j, val in enumerate(predictions[sname]):
            print(f"    [{800 + j}] 0x{val:08x}")

    # weakest.txt
    with open("/app/weakest.txt", "w") as f:
        f.write("gen_beta\n")
    print("\n  Weakest: gen_beta (xorshift128)")
    print("  Reason: Internal state is directly exposed in output values.")
    print("  Only 4 outputs needed to predict all future outputs.")

    # assessment.json — quantitative vulnerability evaluation
    assessment = {
        "generators": {
            "gen_alpha": {
                "algorithm": "mt19937_modified",
                "attack_name": "GF(2) tempering matrix inversion",
                "min_outputs_for_recovery": 624,
                "attack_complexity": "O(n)",
                "state_bits": 19968,
                "output_bits_per_value": 32,
                "attack_successful": True
            },
            "gen_beta": {
                "algorithm": "xorshift128",
                "attack_name": "direct state extraction from output",
                "min_outputs_for_recovery": 4,
                "attack_complexity": "O(1)",
                "state_bits": 128,
                "output_bits_per_value": 32,
                "attack_successful": True
            },
            "gen_gamma": {
                "algorithm": "lcg64_truncated",
                "attack_name": "brute-force lower 32 bits of 64-bit state",
                "min_outputs_for_recovery": 2,
                "attack_complexity": "O(2^32)",
                "state_bits": 64,
                "output_bits_per_value": 32,
                "attack_successful": True
            }
        },
        "ranking_weakest_to_strongest": ["gen_beta", "gen_gamma", "gen_alpha"],
        "ranking_justification": (
            "gen_beta (xorshift128) is weakest: internal state IS the output, "
            "only 4 consecutive values needed for O(1) state recovery. "
            "gen_gamma (truncated LCG64) is medium: output is truncated but "
            "brute-forcing 2^32 lower bits from 2 outputs is feasible in seconds. "
            "gen_alpha (modified MT19937) is strongest: requires 624 outputs and "
            "GF(2) matrix inversion of non-standard tempering parameters."
        )
    }

    with open("/app/assessment.json", "w") as f:
        json.dump(assessment, f, indent=2)
    print("\n  Assessment written to /app/assessment.json")

    print("\nDone.")


if __name__ == "__main__":
    main()

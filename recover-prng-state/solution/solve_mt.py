
"""
Solution for PRNG prediction task.

Step 1: Reverse-engineer the stripped binary /app/token_gen using objdump.
  - The binary contains constants 624, 397, 0x9908B0DF which identify it
    as a Mersenne Twister (MT19937) variant.
  - The tempering section uses non-standard shift/mask values, extracted
    from the disassembly of the extract() function:
      shr $0xd  => shift_u = 13
      shl $0x9, and $0xb5a7c4e0 => shift_s = 9, mask_b = 0xB5A7C4E0
      shl $0x11, and $0xd3e40000 => shift_t = 17, mask_c = 0xD3E40000
      shr $0xf  => shift_l = 15

Step 2: Parse binary captured data (700 LE uint32 values).

Step 3: Construct the 32x32 GF(2) tempering matrix and invert it.

Step 4: Recover internal state from the first 624 outputs using the
  inverse tempering matrix.

Step 5: Apply the MT twist recurrence to advance state, then temper
  state words to predict outputs 700-709.
"""

import struct
import subprocess


# --- Constants extracted from binary analysis (objdump -d /app/token_gen) ---

N = 624
M = 397
MATRIX_A = 0x9908B0DF
UPPER_MASK = 0x80000000
LOWER_MASK = 0x7FFFFFFF

TEMPER_SHIFT_U = 13
TEMPER_SHIFT_S = 9
TEMPER_MASK_B = 0xB5A7C4E0
TEMPER_SHIFT_T = 17
TEMPER_MASK_C = 0xD3E40000
TEMPER_SHIFT_L = 15


def temper(y):
    """Apply the custom tempering transformation."""
    y ^= (y >> TEMPER_SHIFT_U)
    y ^= (y << TEMPER_SHIFT_S) & TEMPER_MASK_B
    y ^= (y << TEMPER_SHIFT_T) & TEMPER_MASK_C
    y ^= (y >> TEMPER_SHIFT_L)
    return y & 0xFFFFFFFF


def build_temper_matrix():
    """Build 32x32 GF(2) matrix by applying temper to each unit vector."""
    mat = [[0] * 32 for _ in range(32)]
    for i in range(32):
        t = temper(1 << (31 - i))
        for j in range(32):
            mat[j][i] = (t >> (31 - j)) & 1
    return mat


def gf2_matrix_inverse(mat):
    """Invert a 32x32 matrix over GF(2) via Gaussian elimination."""
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
            raise ValueError("Matrix not invertible over GF(2)")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(n):
            if row != col and aug[row][col] == 1:
                for k in range(2 * n):
                    aug[row][k] ^= aug[col][k]

    return [row[n:] for row in aug]


def gf2_mat_vec_mul(mat, val):
    """Multiply 32x32 GF(2) matrix by a 32-bit integer."""
    v = [(val >> (31 - i)) & 1 for i in range(32)]
    result = 0
    for i in range(32):
        bit = 0
        for j in range(32):
            bit ^= (mat[i][j] & v[j])
        result |= (bit << (31 - i))
    return result


def untemper(y, inv_matrix):
    """Invert tempering using precomputed GF(2) inverse matrix."""
    return gf2_mat_vec_mul(inv_matrix, y)


def twist(mt):
    """Apply MT19937 twist operation in-place."""
    for i in range(N):
        y = (mt[i] & UPPER_MASK) | (mt[(i + 1) % N] & LOWER_MASK)
        mt[i] = mt[(i + M) % N] ^ (y >> 1)
        if y & 1:
            mt[i] ^= MATRIX_A


def main():
    # Show a snippet of the disassembly for verification
    print("--- Verifying binary analysis ---")
    try:
        result = subprocess.run(
            ['objdump', '-d', '/app/token_gen'],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.split('\n')
        # Look for key constants in disassembly
        for line in lines:
            for pattern in ['9908b0df', 'b5a7c4e0', 'd3e40000']:
                if pattern in line.lower():
                    print(f"  Found constant: {line.strip()}")
                    break
    except Exception as e:
        print(f"  (objdump check skipped: {e})")

    # Read captured binary data
    print("\n--- Reading captured tokens ---")
    with open("/app/captured_tokens.bin", "rb") as f:
        data = f.read()
    observed = list(struct.unpack(f"<{len(data) // 4}I", data))
    print(f"Read {len(observed)} tokens from binary file")
    assert len(observed) == 700, f"Expected 700, got {len(observed)}"

    # Build and invert tempering matrix
    print("\n--- Constructing GF(2) tempering matrix ---")
    T = build_temper_matrix()
    print("Inverting over GF(2)...")
    T_inv = gf2_matrix_inverse(T)

    # Recover internal state from first 624 outputs
    print("\n--- Recovering internal state ---")
    state = [untemper(observed[i], T_inv) for i in range(624)]

    # Verify recovery
    for i in range(624):
        assert temper(state[i]) == observed[i], f"Recovery failed at {i}"
    print("State recovery verified for positions 0-623")

    # Apply twist to advance state
    print("\n--- Applying twist recurrence ---")
    mt = list(state)
    twist(mt)

    # Verify against observed 624-699
    for i in range(76):
        expected = observed[624 + i]
        got = temper(mt[i])
        assert got == expected, (
            f"Post-twist mismatch at {624 + i}: "
            f"expected 0x{expected:08x}, got 0x{got:08x}"
        )
    print("Post-twist verified for positions 624-699")

    # Predict 700-709
    predictions = [temper(mt[i]) for i in range(76, 86)]

    print("\nPredictions for positions 700-709:")
    for i, p in enumerate(predictions):
        print(f"  [{700 + i}] 0x{p:08x}")

    with open("/app/predicted_tokens.txt", "w") as f:
        for p in predictions:
            f.write(f"0x{p:08x}\n")

    print("\nPredictions written to /app/predicted_tokens.txt")


if __name__ == "__main__":
    main()

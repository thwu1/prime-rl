"""
Fix the three bugs in the Dirichlet series pipeline.

Bug 1 (compute.py): ctypes argtypes use c_int (32-bit) — should be c_int64
        for n values exceeding 2^31.

Bug 2 (dirichlet.c, totient_rec): n*(n+1)/2 overflows int64_t for n > ~3e9.
        Must reduce modulo MOD before multiplying, using Fermat modular inverse.

Bug 3 (dirichlet.c, liouville_rec): Initial value of recurrence is 1 instead
        of isqrt_safe(n).  The correct identity is
            L(n) = floor(sqrt(n)) - sum_{d>=2} L(floor(n/d))
"""


def fix_compute_py():
    with open("/app/compute.py", "r") as f:
        content = f.read()
    content = content.replace("ctypes.c_int]", "ctypes.c_int64]")
    with open("/app/compute.py", "w") as f:
        f.write(content)


def fix_dirichlet_c():
    with open("/app/dirichlet.c", "r") as f:
        content = f.read()

    # Fix totient overflow: n*(n+1)/2 -> proper modular reduction
    old_totient = "    int64_t result = (n * (n + 1) / 2) % MOD;"
    new_totient = (
        "    int64_t nm = n % MOD;\n"
        "    int64_t inv2 = mod_pow(2, MOD - 2, MOD);\n"
        "    int64_t result = (__int128)nm * ((n + 1) % MOD) % MOD * inv2 % MOD;"
    )
    content = content.replace(old_totient, new_totient)

    # Fix liouville initial value: 1 -> isqrt_safe(n)
    # Use surrounding context to target only liouville_rec, not mertens_rec
    old_liouville = (
        "    if (set_L[idx]) return memo_L[idx];\n"
        "\n"
        "    int64_t result = 1;"
    )
    new_liouville = (
        "    if (set_L[idx]) return memo_L[idx];\n"
        "\n"
        "    int64_t result = isqrt_safe(n);"
    )
    content = content.replace(old_liouville, new_liouville)

    with open("/app/dirichlet.c", "w") as f:
        f.write(content)


if __name__ == "__main__":
    fix_compute_py()
    fix_dirichlet_c()
    print("All bugs fixed.")

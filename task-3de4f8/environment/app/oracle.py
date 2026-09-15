"""Oracle functions for program synthesis benchmark.

Each oracle takes four 16-bit unsigned integers (a, b, c, d) and returns
a 16-bit unsigned integer.  The synthesizer must discover equivalent DSL
programs without inspecting the oracle source.
"""
import sys

MASK = 0xFFFF


def oracle_1(a, b, c, d):
    return (a ^ b) & MASK


def oracle_2(a, b, c, d):
    t = (a + b) & MASK
    return (t << (c & 0xf)) & MASK


def oracle_3(a, b, c, d):
    t1 = (a * b) & MASK
    t2 = c | d
    return (t1 ^ t2) & MASK


def oracle_4(a, b, c, d):
    t1 = a & b
    t2 = c ^ d
    return (t1 + t2) & MASK


def oracle_5(a, b, c, d):
    t1 = (a + b) & MASK
    t2 = c ^ d
    t3 = (t1 - t2) & MASK
    return (t3 | a) & MASK


ORACLES = {
    1: oracle_1,
    2: oracle_2,
    3: oracle_3,
    4: oracle_4,
    5: oracle_5,
}


def get_oracle(oracle_id):
    """Return the oracle function for the given id."""
    return ORACLES[oracle_id]


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(f"Usage: {sys.argv[0]} <oracle_id> <a> <b> <c> <d>", file=sys.stderr)
        sys.exit(1)
    oid = int(sys.argv[1])
    a, b, c, d = (int(x) & MASK for x in sys.argv[2:6])
    print(get_oracle(oid)(a, b, c, d))

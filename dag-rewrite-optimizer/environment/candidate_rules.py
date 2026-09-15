"""
Six candidate rewrite rules for the DAG optimizer.

All operations use unsigned 32-bit arithmetic (modulo 2^32).
SHL/SHR mask the shift amount to 5 bits: effective_shift = amount & 0x1F.
NEG(x) = (-x) mod 2^32  (two's complement negation).
NOT(x) = ~x & 0xFFFFFFFF  (bitwise complement).
CMPLT(a, b) = 1 if a < b (unsigned comparison), else 0.

Verify each rule using an SMT solver to determine whether it holds
universally or has counterexamples.

"""

CANDIDATE_RULES = {
    "C1": {
        "name": "bit_partition",
        "lhs": "OR(AND(x, CONST(c)), AND(x, CONST(~c & 0xFFFFFFFF)))",
        "rhs": "x",
        "claim": "Partitioning x by a bitmask c and its complement, then OR-combining, yields x.",
        "free_variables": {"x": "uint32"},
        "free_constants": {"c": "uint32"},
    },
    "C2": {
        "name": "shift_roundtrip",
        "lhs": "SHR(SHL(x, CONST(c)), CONST(c))",
        "rhs": "x",
        "claim": "Left-shifting then right-shifting by the same constant recovers the original value.",
        "free_variables": {"x": "uint32"},
        "free_constants": {"c": "integer in [1, 31]"},
    },
    "C3": {
        "name": "increment_compare",
        "lhs": "CMPLT(x, ADD(x, CONST(1)))",
        "rhs": "CONST(1)",
        "claim": "Any unsigned integer is strictly less than itself plus one.",
        "free_variables": {"x": "uint32"},
        "free_constants": {},
    },
    "C4": {
        "name": "sub_inverse",
        "lhs": "SUB(x, SUB(x, y))",
        "rhs": "y",
        "claim": "Subtracting (x - y) from x recovers y.",
        "free_variables": {"x": "uint32", "y": "uint32"},
        "free_constants": {},
    },
    "C5": {
        "name": "additive_inverse",
        "lhs": "ADD(x, NEG(x))",
        "rhs": "CONST(0)",
        "claim": "Adding a value to its two's complement negation yields zero.",
        "free_variables": {"x": "uint32"},
        "free_constants": {},
    },
    "C6": {
        "name": "sub_decreases",
        "lhs": "CMPLT(SUB(x, y), x)",
        "rhs": "CONST(1)",
        "claim": "Subtracting any value from x yields a result strictly less than x.",
        "free_variables": {"x": "uint32", "y": "uint32"},
        "free_constants": {},
    },
}

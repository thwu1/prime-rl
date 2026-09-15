"""
Run Knuth-Bendix completion on the standard group theory axioms.

Group theory is specified by three axioms over the signature {mul, inv, e}:
  - Left identity:   mul(e, x) = x
  - Left inverse:    mul(inv(x), x) = e
  - Associativity:   mul(mul(x, y), z) = mul(x, mul(y, z))

A successful completion should derive additional rules such as right identity,
right inverse, inverse involution, and inverse distribution, producing a
confluent and terminating rewrite system.

"""

from term import Var, Fun
from completion import complete
from rewriting import normalize


def mul(a, b):
    return Fun('mul', (a, b))


def inv(a):
    return Fun('inv', (a,))


e = Fun('e', ())
x, y, z = Var('x'), Var('y'), Var('z')


# The three axioms of group theory
axioms = [
    (mul(e, x), x),                            # left identity
    (mul(inv(x), x), e),                        # left inverse
    (mul(mul(x, y), z), mul(x, mul(y, z))),     # associativity
]

print("=" * 60)
print("Knuth-Bendix Completion for Group Theory")
print("=" * 60)
print()
print("Axioms:")
for lhs, rhs in axioms:
    print(f"  {lhs} = {rhs}")
print()

try:
    rules = complete(axioms)
    print(f"Completion succeeded with {len(rules)} rules:\n")
    for i, (lhs, rhs) in enumerate(rules, 1):
        print(f"  R{i:2d}: {lhs}  -->  {rhs}")
    print()

    # Test normalizations of standard group identities
    a, b = Var('a'), Var('b')

    tests = [
        ("a * e = a",              mul(a, e),                        a),
        ("a * inv(a) = e",         mul(a, inv(a)),                   e),
        ("inv(inv(a)) = a",        inv(inv(a)),                      a),
        ("inv(e) = e",             inv(e),                           e),
        ("inv(a*b) = inv(b)*inv(a)", inv(mul(a, b)),                 mul(inv(b), inv(a))),
        ("inv(a)*(a*b) = b",       mul(inv(a), mul(a, b)),           b),
        ("a*(inv(a)*b) = b",       mul(a, mul(inv(a), b)),           b),
        ("(a*b)*inv(b) = a",       mul(mul(a, b), inv(b)),           a),
    ]

    print("Normalization tests:")
    all_pass = True
    for desc, term, expected in tests:
        result = normalize(term, rules)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  [{status}] {desc}:  {term}  -->  {result}"
              + (f"  (expected: {expected})" if status == "FAIL" else ""))

    print()
    if all_pass:
        print("ALL NORMALIZATION TESTS PASSED")
    else:
        print("SOME NORMALIZATION TESTS FAILED")

except Exception as ex:
    print(f"COMPLETION FAILED: {ex}")
    import traceback
    traceback.print_exc()

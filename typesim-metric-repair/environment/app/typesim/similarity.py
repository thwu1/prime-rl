"""Type similarity computation module.

Implement the TypeSim metric for comparing Python type annotations.
See /app/spec.md for the property specification. Derive the exact
scoring formulas from the specification properties and the 40 test
cases in /app/test_cases.json.
"""

from typesim.parser import TypeNode


def type_similarity(a: TypeNode, b: TypeNode) -> float:
    """Compute TypeSim similarity score between two type nodes.

    Returns a float in [0.0, 1.0] where 1.0 means identical types.

    Design and implement this function according to the property
    specification in /app/spec.md. The function must satisfy:
    - Identity: sim(a, a) = 1.0
    - Symmetry: sim(a, b) = sim(b, a)
    - Bounded:  0.0 <= sim(a, b) <= 1.0

    All 40 test cases in /app/test_cases.json must produce correct
    scores within +/-0.001 tolerance.
    """
    raise NotImplementedError(
        "type_similarity is not implemented. "
        "Design the scoring algorithm according to spec.md properties "
        "and derive exact formulas from the test cases."
    )

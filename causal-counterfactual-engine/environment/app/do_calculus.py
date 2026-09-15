
"""Do-calculus verification for Pearl's causal inference rules."""

from graph_utils import is_d_separated


def verify_rule2(parents_map, X_vars, Z_vars, Y_vars, W_vars):
    """Verify Pearl's do-calculus Rule 2 (Action/Observation Exchange).

    Rule 2 states that under certain graphical conditions, an intervention
    do(Z=z) can be replaced by a mere observation Z=z:

        P(y | do(x), do(z), w) = P(y | do(x), z, w)

    The condition for Rule 2 to hold is:

        (Y ⊥ Z | X ∪ W)  in  G_{X_bar, Z_underline}

    where the mutilated graph G_{X_bar, Z_underline} is obtained from the
    original DAG by:
      - Removing all edges INCOMING to nodes in X  (the "X-bar" operation)
      - Removing all edges OUTGOING from nodes in Z  (the "Z-underline" operation)

    Args:
        parents_map: dict mapping each node to its list of parents,
            defining the original DAG.
        X_vars: set of intervention variables (incoming edges removed).
        Z_vars: set of variables whose do/observe status is being tested.
        Y_vars: set of outcome variables.
        W_vars: set of additional conditioning (observed) variables.

    Returns:
        True if the d-separation condition holds in the mutilated graph
        (i.e., Rule 2 is applicable), False otherwise.

    Raises:
        NotImplementedError: This function is not yet implemented.
    """
    raise NotImplementedError(
        "Implement do-calculus Rule 2 verification."
    )

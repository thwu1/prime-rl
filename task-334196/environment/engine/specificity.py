"""CSS specificity calculator.

Computes selector specificity as a (a, b, c) tuple following
the CSS specification.

"""


def calc_specificity(chain):
    """Calculate CSS specificity of a selector chain.

    Returns (a, b, c) where:
      a = number of ID selectors
      b = number of class selectors + attribute selectors
      c = number of type selectors (excluding universal *)
    """
    a = b = c = 0
    for _, compound in chain:
        if compound.get("id"):
            a += 1
        b += len(compound.get("classes", []))
        b += len(compound.get("attributes", {}))
        t = compound.get("type")
        if t and t != "*":
            c += 1
    return (a, b, c)

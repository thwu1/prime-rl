"""CSS selector specificity calculation per Selectors Level 4."""

from parser import (
    TypeSelector, IDSelector, ClassSelector, AttributeSelector,
    PseudoClassIs, PseudoClassNot, PseudoClassWhere, PseudoClassHas,
)


def specificity_of_compound(compound):
    a, b, c = 0, 0, 0
    for simple in compound.simple_selectors:
        sa, sb, sc = specificity_of_simple(simple)
        a += sa
        b += sb
        c += sc
    return (a, b, c)


def specificity_of_simple(simple):
    if isinstance(simple, IDSelector):
        return (1, 0, 0)
    elif isinstance(simple, ClassSelector):
        return (0, 1, 0)
    elif isinstance(simple, AttributeSelector):
        return (0, 1, 0)
    elif isinstance(simple, TypeSelector):
        if simple.tag == "*":
            return (0, 0, 0)
        return (0, 0, 1)
    elif isinstance(simple, PseudoClassIs):
        return max_specificity_of_selector_list(simple.selectors)
    elif isinstance(simple, PseudoClassNot):
        return max_specificity_of_selector_list(simple.selectors)
    elif isinstance(simple, PseudoClassWhere):
        return (0, 0, 0)
    elif isinstance(simple, PseudoClassHas):
        specs = []
        for rel in simple.relative_selectors:
            specs.append(specificity_of_complex(rel.complex_selector))
        if not specs:
            return (0, 0, 0)
        return max(specs)
    return (0, 0, 0)


def max_specificity_of_selector_list(selectors):
    if not selectors:
        return (0, 0, 0)
    specs = [specificity_of_complex(sel) for sel in selectors]
    return max(specs)


def specificity_of_complex(complex_sel):
    a, b, c = 0, 0, 0
    for compound, _ in complex_sel.parts:
        sa, sb, sc = specificity_of_compound(compound)
        a += sa
        b += sb
        c += sc
    return (a, b, c)

"""CSS selector matching against DOM elements."""

from parser import (
    TypeSelector, IDSelector, ClassSelector, AttributeSelector,
    PseudoClassIs, PseudoClassNot, PseudoClassWhere, PseudoClassHas,
)


def matches_compound(node, compound):
    for simple in compound.simple_selectors:
        if not matches_simple(node, simple):
            return False
    return True


def matches_simple(node, simple):
    if isinstance(simple, TypeSelector):
        return simple.tag == "*" or node.tag == simple.tag
    elif isinstance(simple, IDSelector):
        return node.id == simple.id
    elif isinstance(simple, ClassSelector):
        return simple.cls in node.classes
    elif isinstance(simple, AttributeSelector):
        return matches_attribute(node, simple)
    elif isinstance(simple, PseudoClassIs):
        return any(matches_complex(node, sel) for sel in simple.selectors)
    elif isinstance(simple, PseudoClassNot):
        return not any(matches_complex(node, sel) for sel in simple.selectors)
    elif isinstance(simple, PseudoClassWhere):
        return any(matches_complex(node, sel) for sel in simple.selectors)
    elif isinstance(simple, PseudoClassHas):
        return matches_has(node, simple)
    return False


def matches_attribute(node, attr_sel):
    val = node.attributes.get(attr_sel.attr)
    if val is None:
        return False
    if attr_sel.op is None:
        return True
    if attr_sel.op == "=":
        return val == attr_sel.value
    elif attr_sel.op == "~=":
        return attr_sel.value in val.split()
    elif attr_sel.op == "|=":
        return val == attr_sel.value or val.startswith(attr_sel.value + "-")
    elif attr_sel.op == "^=":
        return val.startswith(attr_sel.value)
    elif attr_sel.op == "$=":
        return val.endswith(attr_sel.value)
    elif attr_sel.op == "*=":
        return attr_sel.value in val
    return False


def matches_has(node, has_sel):
    for rel in has_sel.relative_selectors:
        if rel.combinator == ">":
            for child in node.element_children():
                if matches_complex(child, rel.complex_selector):
                    return True
        else:
            for desc in node.descendants():
                if matches_complex(desc, rel.complex_selector):
                    return True
    return False


def matches_complex(node, complex_sel):
    parts = complex_sel.parts
    if not parts:
        return False

    rightmost_compound = parts[-1][0]
    if not matches_compound(node, rightmost_compound):
        return False

    current_node = node
    for i in range(len(parts) - 2, -1, -1):
        compound, combinator = parts[i]
        if combinator == " ":
            found = False
            for ancestor in current_node.ancestors():
                if matches_compound(ancestor, compound):
                    current_node = ancestor
                    found = True
                    break
            if not found:
                return False
        elif combinator == ">":
            parent = current_node.parent
            if parent is None or not matches_compound(parent, compound):
                return False
            current_node = parent
        elif combinator == "+":
            sib = current_node.immediately_preceding_sibling()
            if sib is None or not matches_compound(sib, compound):
                return False
            current_node = sib
        elif combinator == "~":
            found = False
            for sib in current_node.preceding_siblings():
                if matches_compound(sib, compound):
                    current_node = sib
                    found = True
                    break
            if not found:
                return False
    return True

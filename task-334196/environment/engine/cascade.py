"""CSS cascade resolution.

Resolves competing declarations for the same property according to
the CSS cascade: origin, importance, specificity, and source order.

"""


def _cascade_priority(important, origin):
    """Return a numeric priority for cascade sorting.

    Higher number = higher priority.
    """
    if important:
        if origin == "user-agent":
            return 6
        if origin == "user":
            return 5
        if origin == "author":
            return 4
    else:
        if origin == "author":
            return 3
        if origin == "user":
            return 2
        if origin == "user-agent":
            return 1
    return 0


def resolve_cascade(matching_declarations):
    """Resolve CSS cascade for a set of declarations targeting one element.

    Each declaration dict has: property, value, important, origin,
    specificity, source_order.

    Returns a dict mapping property names to their winning values.
    """
    by_prop = {}
    for decl in matching_declarations:
        prop = decl["property"]
        by_prop.setdefault(prop, []).append(decl)

    result = {}
    for prop, decls in by_prop.items():
        def sort_key(d):
            pri = _cascade_priority(d["important"], d["origin"])
            return (pri, d["specificity"], d["source_order"])
        decls.sort(key=sort_key, reverse=True)
        result[prop] = decls[0]["value"]
    return result

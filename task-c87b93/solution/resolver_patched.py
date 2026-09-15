"""CSS cascade resolution with inheritance, var() substitution, and calc()."""

from dom import collect_elements, DOMNode
from specificity import specificity_of_complex
from matcher import matches_complex
from inheritance import apply_inheritance
from value_resolver import resolve_var_references, resolve_math_functions


def resolve_cascade(dom_root, rules):
    # Phase 1: flat cascade (per-element, no inheritance)
    elements = collect_elements(dom_root)
    raw = {}

    for element in elements:
        applicable = []
        for rule in rules:
            for selector in rule.selectors:
                if matches_complex(element, selector):
                    spec = specificity_of_complex(selector)
                    for di, decl in enumerate(rule.declarations):
                        applicable.append((
                            1 if decl.important else 0,
                            spec,
                            rule.source_order,
                            di,
                            decl,
                        ))
        if not applicable:
            continue

        props = {}
        for importance, spec, source_order, decl_idx, decl in applicable:
            key = decl.property
            if key not in props:
                props[key] = []
            props[key].append((importance, spec, source_order, decl_idx, decl))

        resolved = {}
        for prop, entries in props.items():
            entries.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
            winner = entries[-1]
            resolved[prop] = winner[4].value

        if resolved:
            path = element.full_path()
            if path in raw:
                raw[path].update(resolved)
            else:
                raw[path] = resolved

    # Phase 2: top-down tree walk — inheritance + var() + calc()
    result = {}
    _resolve_tree(dom_root, raw, {}, result)
    return result


def _resolve_tree(node, raw, parent_computed, result):
    if not isinstance(node, DOMNode):
        return

    # 1. Cascade + inheritance
    computed = apply_inheritance(node, raw, parent_computed)

    # 2. Collect custom properties and resolve var() within them
    custom_props = {k: v for k, v in computed.items() if k.startswith('--')}
    resolved_custom = {}
    for prop, val in custom_props.items():
        if val is None:
            resolved_custom[prop] = None
        else:
            resolved_custom[prop] = resolve_var_references(val, custom_props)

    # 3. Resolve var() and calc() in regular properties
    final = {}
    for prop, val in computed.items():
        if prop.startswith('--'):
            final[prop] = resolved_custom.get(prop)
        else:
            resolved = resolve_var_references(val, resolved_custom)
            if resolved is not None:
                resolved = resolve_math_functions(resolved)
                final[prop] = resolved

    # 4. Build output (exclude custom props and empty values)
    output = {k: v for k, v in final.items()
              if not k.startswith('--') and v is not None and v != ''}
    if output:
        result[node.full_path()] = output

    # 5. Recurse — children see fully resolved computed values
    for child in node.children:
        if isinstance(child, DOMNode):
            _resolve_tree(child, raw, final, result)

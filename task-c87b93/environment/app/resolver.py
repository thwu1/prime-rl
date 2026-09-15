"""CSS cascade resolution — determines winning declarations per element."""

from dom import collect_elements
from specificity import specificity_of_complex
from matcher import matches_complex


def resolve_cascade(dom_root, rules):
    elements = collect_elements(dom_root)
    result = {}

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
            if path in result:
                result[path].update(resolved)
            else:
                result[path] = resolved

    return result

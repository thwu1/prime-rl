"""CSS computed style calculation.

Ties together parsing, matching, cascade, and inheritance to produce
final computed styles for every node in a DOM tree.

"""

import json
import os
import sys


def load_dom(path):
    """Load DOM tree from JSON file."""
    with open(path) as f:
        return json.load(f)


def load_rules(path):
    """Load CSS rules from JSON file."""
    with open(path) as f:
        return json.load(f)


def load_properties(path):
    """Load CSS property metadata from JSON file."""
    with open(path) as f:
        return json.load(f)


def build_dom_index(dom, parent_id=None, index=None):
    """Build a flat lookup index from a nested DOM tree.

    Returns dict mapping node_id -> {tag, id, classes, attributes,
    parent_id, children_ids}.
    """
    if index is None:
        index = {}
    nid = dom["node_id"]
    index[nid] = {
        "tag": dom["tag"],
        "id": dom.get("id"),
        "classes": dom.get("classes", []),
        "attributes": dom.get("attributes", {}),
        "parent_id": parent_id,
        "children_ids": [c["node_id"] for c in dom.get("children", [])],
    }
    for child in dom.get("children", []):
        build_dom_index(child, nid, index)
    return index


def _tree_order(dom):
    """Return node IDs in depth-first (tree) order."""
    order = []

    def dfs(node):
        order.append(node["node_id"])
        for child in node.get("children", []):
            dfs(child)

    dfs(dom)
    return order


def compute_styles(dom, rules, properties_meta):
    """Compute final styles for every node in the DOM tree.

    Returns dict mapping node_id (int) -> dict of property -> computed value.
    """
    from engine.parser import parse_selector
    from engine.specificity import calc_specificity
    from engine.matcher import match_selector
    from engine.shorthand import expand_shorthand
    from engine.cascade import resolve_cascade, _cascade_priority

    dom_index = build_dom_index(dom)

    parsed_rules = []
    for rule in rules:
        chains = parse_selector(rule["selector"])
        for chain in chains:
            spec = calc_specificity(chain)
            parsed_rules.append({
                "chain": chain,
                "specificity": spec,
                "declarations": rule["declarations"],
                "origin": rule["origin"],
                "source_order": rule["source_order"],
            })

    debug = os.environ.get("STYLE_DEBUG") == "1"
    node_order = _tree_order(dom)
    computed = {}

    for node_id in node_order:
        node_info = dom_index[node_id]

        all_decls = []
        for prule in parsed_rules:
            if match_selector(prule["chain"], node_id, dom_index):
                for decl in prule["declarations"]:
                    expanded = expand_shorthand(decl["property"], decl["value"])
                    for prop, val in expanded.items():
                        all_decls.append({
                            "property": prop,
                            "value": val,
                            "important": decl["important"],
                            "origin": prule["origin"],
                            "specificity": prule["specificity"],
                            "source_order": prule["source_order"],
                        })

        cascaded = resolve_cascade(all_decls)

        if debug:
            props_seen = {}
            for decl in all_decls:
                p = decl["property"]
                props_seen.setdefault(p, []).append(decl)
            for p in sorted(props_seen):
                for d in props_seen[p]:
                    pri = _cascade_priority(d["important"], d["origin"])
                    spec_str = ",".join(str(x) for x in d["specificity"])
                    print(
                        f"TRACE node={node_id} tag={node_info['tag']} "
                        f"prop={p} val={d['value']} origin={d['origin']} "
                        f"imp={d['important']} spec={spec_str} "
                        f"src={d['source_order']} pri={pri}",
                        file=sys.stderr,
                    )
                if p in cascaded:
                    print(
                        f"WINNER node={node_id} prop={p} val={cascaded[p]}",
                        file=sys.stderr,
                    )

        parent_id = node_info["parent_id"]
        parent_styles = (
            computed.get(parent_id, {}) if parent_id is not None else {}
        )

        final = {}
        for prop, meta in properties_meta.items():
            if prop in cascaded:
                val = cascaded[prop]
                if val == "inherit":
                    final[prop] = parent_styles.get(prop, meta["initial"])
                elif val == "initial":
                    final[prop] = meta["initial"]
                else:
                    final[prop] = val
            elif meta["inherited"]:
                final[prop] = parent_styles.get(prop, meta["initial"])
            else:
                final[prop] = meta["initial"]

        computed[node_id] = final

    return computed

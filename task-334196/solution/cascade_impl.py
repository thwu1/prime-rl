"""CSS Cascade and Inheritance Resolver — Full Implementation.

"""

import json


def load_dom(path):
    with open(path) as f:
        return json.load(f)


def load_rules(path):
    with open(path) as f:
        return json.load(f)


def load_properties(path):
    with open(path) as f:
        return json.load(f)


# ── DOM index ────────────────────────────────────────────────────────

def build_dom_index(dom, parent_id=None, index=None):
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


# ── Selector parsing ────────────────────────────────────────────────

def _parse_compound(s):
    """Parse a compound selector string like 'div.foo#bar[attr="v"]'."""
    result = {"type": None, "id": None, "classes": [], "attributes": {}}
    i = 0
    n = len(s)
    # type selector
    if i < n and (s[i].isalpha() or s[i] == "*"):
        if s[i] == "*":
            result["type"] = "*"
            i += 1
        else:
            j = i
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            result["type"] = s[i:j]
            i = j
    while i < n:
        if s[i] == "#":
            i += 1
            j = i
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            result["id"] = s[i:j]
            i = j
        elif s[i] == ".":
            i += 1
            j = i
            while j < n and (s[j].isalnum() or s[j] in "-_"):
                j += 1
            result["classes"].append(s[i:j])
            i = j
        elif s[i] == "[":
            i += 1
            j = i
            while j < n and s[j] not in "=]":
                j += 1
            attr_name = s[i:j].strip()
            attr_value = None
            if j < n and s[j] == "=":
                j += 1
                if j < n and s[j] in "\"'":
                    q = s[j]
                    j += 1
                    k = j
                    while k < n and s[k] != q:
                        k += 1
                    attr_value = s[j:k]
                    j = k + 1
                else:
                    k = j
                    while k < n and s[k] != "]":
                        k += 1
                    attr_value = s[j:k].strip()
                    j = k
            if j < n and s[j] == "]":
                j += 1
            result["attributes"][attr_name] = attr_value
            i = j
        else:
            break
    return result


def _tokenize_group(s):
    """Tokenize one selector group into compounds and combinators."""
    tokens = []
    i = 0
    n = len(s)
    while i < n:
        # skip whitespace
        ws_start = i
        while i < n and s[i] in " \t":
            i += 1
        had_ws = i > ws_start
        if i >= n:
            break
        if s[i] == ">":
            tokens.append(("comb", ">"))
            i += 1
            continue
        # read compound (respecting brackets and quotes)
        start = i
        in_brackets = False
        in_quotes = False
        qchar = None
        while i < n:
            c = s[i]
            if in_quotes:
                if c == qchar:
                    in_quotes = False
                i += 1
                continue
            if c in "\"'":
                in_quotes = True
                qchar = c
                i += 1
                continue
            if c == "[":
                in_brackets = True
                i += 1
                continue
            if c == "]":
                in_brackets = False
                i += 1
                continue
            if in_brackets:
                i += 1
                continue
            if c in " \t>":
                break
            i += 1
        compound_str = s[start:i]
        if compound_str:
            if had_ws and tokens and tokens[-1][0] == "comp":
                tokens.append(("comb", " "))
            tokens.append(("comp", compound_str))
    return tokens


def parse_selector(selector_str):
    chains = []
    for group in selector_str.split(","):
        group = group.strip()
        if not group:
            continue
        tokens = _tokenize_group(group)
        compounds = []
        combinators = []
        for ttype, tval in tokens:
            if ttype == "comp":
                compounds.append(_parse_compound(tval))
            else:
                combinators.append(tval)
        # build chain: list of (combinator, compound)
        # stored left-to-right; combinator at index i connects compound[i] to compound[i+1]
        chain = []
        for idx in range(len(compounds)):
            comb = combinators[idx] if idx < len(combinators) else None
            chain.append((comb, compounds[idx]))
        chains.append(chain)
    return chains


# ── Specificity ──────────────────────────────────────────────────────

def calc_specificity(chain):
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


# ── Selector matching ───────────────────────────────────────────────

def _match_compound(compound, node_info):
    t = compound.get("type")
    if t and t != "*" and t != node_info["tag"]:
        return False
    if compound.get("id") and compound["id"] != node_info.get("id"):
        return False
    for cls in compound.get("classes", []):
        if cls not in node_info.get("classes", []):
            return False
    for attr_name, attr_value in compound.get("attributes", {}).items():
        node_attrs = node_info.get("attributes", {})
        if attr_name not in node_attrs:
            return False
        if attr_value is not None and node_attrs[attr_name] != attr_value:
            return False
    return True


def match_selector(chain, node_id, dom_index):
    if not chain:
        return False
    # Match rightmost compound against the target node
    last_idx = len(chain) - 1
    _, last_compound = chain[last_idx]
    if not _match_compound(last_compound, dom_index[node_id]):
        return False
    # Walk leftward through the chain
    current_id = node_id
    for i in range(last_idx - 1, -1, -1):
        comb, compound = chain[i]
        # The combinator at chain[i] connects compound[i] -> compound[i+1]
        # We already matched compound[i+1] at current_id
        # Now we need compound[i] to be an ancestor (space) or parent (>) of current_id
        if comb == ">":
            parent_id = dom_index[current_id]["parent_id"]
            if parent_id is None or not _match_compound(compound, dom_index[parent_id]):
                return False
            current_id = parent_id
        elif comb == " ":
            anc_id = dom_index[current_id]["parent_id"]
            while anc_id is not None:
                if _match_compound(compound, dom_index[anc_id]):
                    break
                anc_id = dom_index[anc_id]["parent_id"]
            if anc_id is None:
                return False
            current_id = anc_id
        else:
            return False
    return True


# ── Shorthand expansion ─────────────────────────────────────────────

def expand_shorthand(property_name, value):
    if property_name in ("margin", "padding"):
        parts = value.split()
        prefix = property_name
        if len(parts) == 1:
            v = parts[0]
            return {f"{prefix}-top": v, f"{prefix}-right": v,
                    f"{prefix}-bottom": v, f"{prefix}-left": v}
        elif len(parts) == 2:
            return {f"{prefix}-top": parts[0], f"{prefix}-right": parts[1],
                    f"{prefix}-bottom": parts[0], f"{prefix}-left": parts[1]}
        elif len(parts) == 3:
            return {f"{prefix}-top": parts[0], f"{prefix}-right": parts[1],
                    f"{prefix}-bottom": parts[2], f"{prefix}-left": parts[1]}
        elif len(parts) == 4:
            return {f"{prefix}-top": parts[0], f"{prefix}-right": parts[1],
                    f"{prefix}-bottom": parts[2], f"{prefix}-left": parts[3]}
    return {property_name: value}


# ── Cascade resolution ──────────────────────────────────────────────

def _cascade_priority(important, origin):
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


# ── Compute styles ──────────────────────────────────────────────────

def _tree_order(dom):
    order = []
    def dfs(node):
        order.append(node["node_id"])
        for child in node.get("children", []):
            dfs(child)
    dfs(dom)
    return order


def compute_styles(dom, rules, properties_meta):
    dom_index = build_dom_index(dom)

    # Parse all selectors; for selector lists, each alternative becomes its own entry
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

    node_order = _tree_order(dom)
    computed = {}

    for node_id in node_order:
        node_info = dom_index[node_id]

        # Collect all matching longhand declarations
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

        parent_id = node_info["parent_id"]
        parent_styles = computed.get(parent_id, {}) if parent_id is not None else {}

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


if __name__ == "__main__":
    dom = load_dom("/app/dom.json")
    rules = load_rules("/app/rules.json")
    props = load_properties("/app/properties.json")
    styles = compute_styles(dom, rules, props)
    print(json.dumps(styles, indent=2, sort_keys=True))

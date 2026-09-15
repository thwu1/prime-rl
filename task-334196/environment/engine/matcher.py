"""CSS selector matching against DOM nodes.

"""


def _match_compound(compound, node_info):
    """Check if a single compound selector matches a DOM node."""
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
    """Check if a selector chain matches a DOM node.

    Walks the chain right-to-left, matching the rightmost compound
    against the target node and then walking the DOM tree according
    to each combinator (child '>' or descendant ' ').
    """
    if not chain:
        return False
    last_idx = len(chain) - 1
    _, last_compound = chain[last_idx]
    if not _match_compound(last_compound, dom_index[node_id]):
        return False
    current_id = node_id
    for i in range(last_idx - 1, -1, -1):
        comb, compound = chain[i]
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

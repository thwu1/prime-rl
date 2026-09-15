#!/usr/bin/env python3
"""BGP Best-Path Selection Engine - Solution Implementation

"""

from typing import List, Dict, Optional, Tuple


def _ip_to_int(ip: str) -> int:
    """Convert dotted-decimal IP to integer for comparison."""
    parts = ip.split(".")
    return (int(parts[0]) << 24) | (int(parts[1]) << 16) | (int(parts[2]) << 8) | int(parts[3])


def _compute_as_path_length(as_path: List[Dict]) -> int:
    """Compute effective AS-path length per BGP rules.

    AS_SEQUENCE: each AS counts as 1
    AS_SET: counts as 1 total
    AS_CONFED_SEQUENCE: not counted
    AS_CONFED_SET: not counted
    """
    length = 0
    for segment in as_path:
        stype = segment["type"]
        if stype == "AS_SEQUENCE":
            length += len(segment["asns"])
        elif stype == "AS_SET":
            length += 1
        # AS_CONFED_SEQUENCE and AS_CONFED_SET: no contribution
    return length


def _get_neighbor_as(as_path: List[Dict]) -> Optional[int]:
    """Get the first AS in the first AS_SEQUENCE segment, skipping confed segments.

    This is the 'neighbor AS' used for MED comparison.
    """
    for segment in as_path:
        if segment["type"] in ("AS_CONFED_SEQUENCE", "AS_CONFED_SET"):
            continue
        if segment["type"] in ("AS_SEQUENCE", "AS_SET"):
            if segment["asns"]:
                return segment["asns"][0]
    return None


def _is_confed_only(as_path: List[Dict]) -> bool:
    """Check if AS path consists only of confederation segments."""
    for segment in as_path:
        if segment["type"] not in ("AS_CONFED_SEQUENCE", "AS_CONFED_SET"):
            return False
    return True


def _get_effective_med(route: Dict, config: Dict) -> int:
    """Get effective MED value, handling missing MED."""
    med = route.get("med")
    if med is None:
        if config.get("med_missing_as_worst", False):
            return 4294967295
        return 0
    return med


def _origin_value(origin: str) -> int:
    """Map origin string to numeric value. Lower is better."""
    return {"igp": 0, "egp": 1, "incomplete": 2}.get(origin.lower(), 2)


def _is_ebgp(route: Dict) -> bool:
    """True if path is from a true eBGP peer (not confederation)."""
    return route.get("path_source") == "ebgp"


def _get_effective_rid(route: Dict) -> str:
    """Get effective router ID: originator_id if present, else router_id."""
    oid = route.get("originator_id")
    if oid:
        return oid
    return route.get("router_id", "0.0.0.0")


def _compare_paths(a: Dict, b: Dict, config: Dict) -> int:
    """Compare two BGP paths. Returns -1 if a better, +1 if b better, 0 if tied."""

    # Step 1: Highest weight
    aw = a.get("weight", 0)
    bw = b.get("weight", 0)
    if aw != bw:
        return -1 if aw > bw else 1

    # Step 2: Highest local_pref
    alp = a.get("local_pref")
    blp = b.get("local_pref")
    alp = 100 if alp is None else alp
    blp = 100 if blp is None else blp
    if alp != blp:
        return -1 if alp > blp else 1

    # Step 3: Locally originated
    a_local = a.get("locally_originated", False)
    b_local = b.get("locally_originated", False)
    if a_local != b_local:
        return -1 if a_local else 1
    if a_local and b_local:
        type_prio = {"network": 0, "redistribute": 0, "aggregate": 1}
        ap = type_prio.get(a.get("local_origin_type", "network"), 1)
        bp = type_prio.get(b.get("local_origin_type", "network"), 1)
        if ap != bp:
            return -1 if ap < bp else 1

    # Step 4: Shortest AS-path
    if not config.get("as_path_ignore", False):
        al = _compute_as_path_length(a.get("as_path", []))
        bl = _compute_as_path_length(b.get("as_path", []))
        if al != bl:
            return -1 if al < bl else 1

    # Step 5: Lowest origin
    ao = _origin_value(a.get("origin", "incomplete"))
    bo = _origin_value(b.get("origin", "incomplete"))
    if ao != bo:
        return -1 if ao < bo else 1

    # Step 6: Lowest MED (conditional)
    compare_med = False
    if config.get("always_compare_med", False):
        compare_med = True
    elif config.get("med_confed", False) and _is_confed_only(a.get("as_path", [])) and _is_confed_only(b.get("as_path", [])):
        compare_med = True
    else:
        a_nas = _get_neighbor_as(a.get("as_path", []))
        b_nas = _get_neighbor_as(b.get("as_path", []))
        if a_nas is not None and b_nas is not None and a_nas == b_nas:
            compare_med = True

    if compare_med:
        am = _get_effective_med(a, config)
        bm = _get_effective_med(b, config)
        if am != bm:
            return -1 if am < bm else 1

    # Step 7: eBGP over iBGP (confed = internal)
    a_ext = _is_ebgp(a)
    b_ext = _is_ebgp(b)
    if a_ext != b_ext:
        return -1 if a_ext else 1

    # Step 8: Lowest IGP metric
    aigp = a.get("igp_metric", 0)
    bigp = b.get("igp_metric", 0)
    if aigp != bigp:
        return -1 if aigp < bigp else 1

    # Step 9: Multipath — skip

    # Step 10: Oldest path (both external only)
    if not config.get("compare_routerid", False):
        if a_ext and b_ext:
            a_rid_eff = _get_effective_rid(a)
            b_rid_eff = _get_effective_rid(b)
            if a_rid_eff != b_rid_eff:
                a_arr = a.get("arrival_order", 0)
                b_arr = b.get("arrival_order", 0)
                if a_arr != b_arr:
                    return -1 if a_arr < b_arr else 1

    # Step 11: Lowest router ID (originator_id substituted)
    a_rid = _ip_to_int(_get_effective_rid(a))
    b_rid = _ip_to_int(_get_effective_rid(b))
    if a_rid != b_rid:
        return -1 if a_rid < b_rid else 1

    # Step 12: Shortest cluster list
    acl = len(a.get("cluster_list", []))
    bcl = len(b.get("cluster_list", []))
    if acl != bcl:
        return -1 if acl < bcl else 1

    # Step 13: Lowest neighbor address
    ana = _ip_to_int(a.get("neighbor_address", "0.0.0.0"))
    bna = _ip_to_int(b.get("neighbor_address", "0.0.0.0"))
    if ana != bna:
        return -1 if ana < bna else 1

    return 0


def select_best_path(scenario: dict) -> int:
    """Select the best BGP path from candidate routes.

    Args:
        scenario: dict with 'config' and 'routes' keys.

    Returns:
        0-based index of the best path, or -1 if no valid paths.
    """
    config = scenario.get("config", {})
    routes = scenario.get("routes", [])

    valid = [(i, r) for i, r in enumerate(routes) if r.get("is_valid", True)]
    if not valid:
        return -1

    if config.get("deterministic_med", False):
        return _select_deterministic_med(config, valid)

    best_idx, best_route = valid[0]
    for idx, route in valid[1:]:
        if _compare_paths(best_route, route, config) > 0:
            best_idx = idx
            best_route = route
    return best_idx


def _select_deterministic_med(config: Dict, valid: List[Tuple[int, Dict]]) -> int:
    """Deterministic MED: group by neighbor AS, select within, compare winners."""
    groups: Dict = {}
    for idx, route in valid:
        nas = _get_neighbor_as(route.get("as_path", []))
        key = nas  # None is a valid key
        if key not in groups:
            groups[key] = []
        groups[key].append((idx, route))

    # Within each group, select best using standard algorithm
    winners = []
    for _, group_routes in groups.items():
        best_idx, best_route = group_routes[0]
        for idx, route in group_routes[1:]:
            if _compare_paths(best_route, route, config) > 0:
                best_idx = idx
                best_route = route
        winners.append((best_idx, best_route))

    # Compare group winners
    best_idx, best_route = winners[0]
    for idx, route in winners[1:]:
        if _compare_paths(best_route, route, config) > 0:
            best_idx = idx
            best_route = route
    return best_idx

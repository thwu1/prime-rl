#!/usr/bin/env python3
"""
Legal predicate comparison engine.

Integrates predicate data from YAML holdings and SQLite term database,
uses pint for unit conversion, and computes semantic relationships
(equivalence, implication, contradiction).
"""

import json
import sqlite3
import sys
from itertools import permutations, product

import yaml
from pint import UnitRegistry

ureg = UnitRegistry()
Q_ = ureg.Quantity

SIGN_FLIP = {">=": "<", ">": "<=", "<=": ">", "<": ">="}


def load_predicates_from_yaml(filepath):
    """Extract predicates from YAML holdings file."""
    with open(filepath) as f:
        data = yaml.safe_load(f)

    predicates = {}
    for opinion in data["opinions"]:
        for fact in opinion["facts"]:
            pid = fact["predicate_id"]
            pred = {
                "id": pid,
                "template": fact["template"],
                "truth": fact.get("truth", True),
                "comparison": None,
            }
            if "quantity" in fact:
                q = fact["quantity"]
                pred["comparison"] = {
                    "sign": q["sign"],
                    "value": q["magnitude"],
                    "unit": q["unit"],
                }
            predicates[pid] = pred
    return predicates


def load_terms_from_db(db_path):
    """Load term assignments and interchangeable groups from SQLite."""
    conn = sqlite3.connect(db_path)

    terms = {}
    for row in conn.execute(
        "SELECT predicate_id, position, term_name, is_generic "
        "FROM predicate_terms ORDER BY predicate_id, position"
    ):
        pid, pos, name, generic = row
        if pid not in terms:
            terms[pid] = []
        terms[pid].append({"name": name, "generic": bool(generic)})

    groups = {}
    for row in conn.execute(
        "SELECT predicate_id, group_index, position "
        "FROM interchangeable_groups ORDER BY predicate_id, group_index, position"
    ):
        pid, gidx, pos = row
        if pid not in groups:
            groups[pid] = {}
        if gidx not in groups[pid]:
            groups[pid][gidx] = []
        groups[pid][gidx].append(pos)

    conn.close()

    groups_list = {}
    for pid, gdict in groups.items():
        groups_list[pid] = [gdict[k] for k in sorted(gdict.keys())]

    return terms, groups_list


def merge_predicate_data(yaml_preds, terms_map, groups_map):
    """Merge YAML predicate data with SQLite term/group data."""
    predicates = []
    for pid in sorted(yaml_preds.keys()):
        pred = yaml_preds[pid]
        pred["terms"] = terms_map.get(pid, [])
        pred["interchangeable_groups"] = groups_map.get(pid, [])
        predicates.append(pred)
    return predicates


def convert_value(value, from_unit, to_unit):
    """Convert a numeric value between compatible physical units using pint."""
    q = Q_(value, from_unit)
    converted = q.to(to_unit)
    return float(converted.magnitude)


def normalize_predicate(pred):
    """Normalize truth=false comparison predicates by flipping the sign."""
    p = {k: v for k, v in pred.items()}
    if p.get("comparison") and p["truth"] is False:
        comp = dict(p["comparison"])
        comp["sign"] = SIGN_FLIP[comp["sign"]]
        p["comparison"] = comp
        p["truth"] = True
    return p


def templates_match(pa, pb):
    """Check template compatibility."""
    if pa["template"] != pb["template"]:
        return False
    if len(pa["terms"]) != len(pb["terms"]):
        return False
    has_a = pa.get("comparison") is not None
    has_b = pb.get("comparison") is not None
    return has_a == has_b


def term_implies(ta, tb):
    """Check if entity term ta can map to tb in a directed implication."""
    if ta["generic"]:
        return True
    if tb["generic"]:
        return False
    return ta["name"] == tb["name"]


def get_permutations(terms, groups):
    """Generate all meaning-preserving reorderings of term indices."""
    n = len(terms)
    if not groups:
        yield list(range(n))
        return

    group_perms = []
    for group in groups:
        group_perms.append(list(permutations(group)))

    base = list(range(n))
    for combo in product(*group_perms):
        perm = list(base)
        for group, gp in zip(groups, combo):
            for orig_pos, new_idx in zip(group, gp):
                perm[orig_pos] = new_idx
        yield perm


def find_valid_register(terms_a, terms_b, perm_a, perm_b, check_fn):
    """Try to build a consistent bijective context register."""
    forward = {}
    reverse = {}
    for i in range(len(terms_a)):
        a_idx = perm_a[i]
        b_idx = perm_b[i]
        if not check_fn(terms_a[a_idx], terms_b[b_idx]):
            return None
        if a_idx in forward and forward[a_idx] != b_idx:
            return None
        if b_idx in reverse and reverse[b_idx] != a_idx:
            return None
        forward[a_idx] = b_idx
        reverse[b_idx] = a_idx
    return forward


def has_valid_register(pa, pb, check_fn):
    """Check if any combination of permutations yields a valid register."""
    perms_a = list(get_permutations(pa["terms"], pa.get("interchangeable_groups", [])))
    perms_b = list(get_permutations(pb["terms"], pb.get("interchangeable_groups", [])))
    for perm_a in perms_a:
        for perm_b in perms_b:
            if find_valid_register(
                pa["terms"], pb["terms"], perm_a, perm_b, check_fn
            ) is not None:
                return True
    return False


def is_lower_bounded(sign):
    return sign in (">=", ">")


def is_upper_bounded(sign):
    return sign in ("<=", "<")


def range_contained(comp_a, comp_b):
    """Check if Range(comp_a) is contained in Range(comp_b) using pint."""
    val_a = comp_a["value"]
    val_b = comp_b["value"]

    if comp_a["unit"] != comp_b["unit"]:
        val_a = convert_value(comp_a["value"], comp_a["unit"], comp_b["unit"])

    sa, sb = comp_a["sign"], comp_b["sign"]

    if is_lower_bounded(sa) and is_lower_bounded(sb):
        if sa == ">=" and sb == ">=":
            return val_a >= val_b
        if sa == ">=" and sb == ">":
            return val_a > val_b
        if sa == ">" and sb == ">=":
            return val_a >= val_b
        if sa == ">" and sb == ">":
            return val_a >= val_b
    elif is_upper_bounded(sa) and is_upper_bounded(sb):
        if sa == "<=" and sb == "<=":
            return val_a <= val_b
        if sa == "<=" and sb == "<":
            return val_a < val_b
        if sa == "<" and sb == "<=":
            return val_a <= val_b
        if sa == "<" and sb == "<":
            return val_a <= val_b
    return False


def ranges_disjoint(comp_a, comp_b):
    """Check if Range(comp_a) and Range(comp_b) are disjoint using pint."""
    val_a = comp_a["value"]
    val_b = comp_b["value"]

    if comp_a["unit"] != comp_b["unit"]:
        val_a = convert_value(comp_a["value"], comp_a["unit"], comp_b["unit"])

    sa, sb = comp_a["sign"], comp_b["sign"]

    if is_lower_bounded(sa) and is_lower_bounded(sb):
        return False
    if is_upper_bounded(sa) and is_upper_bounded(sb):
        return False

    if is_lower_bounded(sa) and is_upper_bounded(sb):
        lo_sign, lo_val = sa, val_a
        hi_sign, hi_val = sb, val_b
    else:
        lo_sign, lo_val = sb, val_b
        hi_sign, hi_val = sa, val_a

    if lo_sign == ">=" and hi_sign == "<=":
        return lo_val > hi_val
    if lo_sign == ">=" and hi_sign == "<":
        return lo_val >= hi_val
    if lo_sign == ">" and hi_sign == "<=":
        return lo_val >= hi_val
    if lo_sign == ">" and hi_sign == "<":
        return lo_val >= hi_val
    return False


def truth_implies(ta, tb):
    if tb is None:
        return True
    if ta is None:
        return False
    return ta == tb


def truth_contradicts(ta, tb):
    if ta is None or tb is None:
        return False
    return ta != tb


def check_implication(pa, pb):
    if not templates_match(pa, pb):
        return False
    if pa.get("comparison"):
        if not range_contained(pa["comparison"], pb["comparison"]):
            return False
    else:
        if not truth_implies(pa["truth"], pb["truth"]):
            return False
    return has_valid_register(pa, pb, term_implies)


def check_contradiction(pa, pb):
    if not templates_match(pa, pb):
        return False
    if pa.get("comparison"):
        if not ranges_disjoint(pa["comparison"], pb["comparison"]):
            return False
    else:
        if not truth_contradicts(pa["truth"], pb["truth"]):
            return False
    return (
        has_valid_register(pa, pb, term_implies)
        or has_valid_register(pb, pa, term_implies)
    )


def write_sqlite_results(db_path, equivalences, implications, contradictions):
    """Write results to SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE IF EXISTS relationships")
    conn.execute(
        "CREATE TABLE relationships ("
        "id_a TEXT NOT NULL, "
        "id_b TEXT NOT NULL, "
        "relation TEXT NOT NULL, "
        "PRIMARY KEY (id_a, id_b, relation))"
    )

    for pair in equivalences:
        conn.execute(
            "INSERT INTO relationships VALUES (?, ?, 'equivalent')",
            (pair[0], pair[1]),
        )
    for pair in implications:
        conn.execute(
            "INSERT INTO relationships VALUES (?, ?, 'implies')",
            (pair[0], pair[1]),
        )
    for pair in contradictions:
        conn.execute(
            "INSERT INTO relationships VALUES (?, ?, 'contradicts')",
            (pair[0], pair[1]),
        )

    conn.commit()
    conn.close()


def main():
    # Load and merge data from YAML + SQLite
    yaml_preds = load_predicates_from_yaml("/app/holdings.yaml")
    terms_map, groups_map = load_terms_from_db("/app/terms.db")
    raw = merge_predicate_data(yaml_preds, terms_map, groups_map)

    print(f"Loaded {len(raw)} predicates from YAML + SQLite", file=sys.stderr)

    predicates = [normalize_predicate(p) for p in raw]
    n = len(predicates)

    equivalences = []
    implications = []
    contradictions = []

    for i in range(n):
        for j in range(i + 1, n):
            pa, pb = predicates[i], predicates[j]
            id_a, id_b = pa["id"], pb["id"]

            a_impl_b = check_implication(pa, pb)
            b_impl_a = check_implication(pb, pa)
            contra = check_contradiction(pa, pb)

            if a_impl_b and b_impl_a:
                equivalences.append(sorted([id_a, id_b]))
            else:
                if a_impl_b:
                    implications.append([id_a, id_b])
                if b_impl_a:
                    implications.append([id_b, id_a])

            if contra:
                contradictions.append(sorted([id_a, id_b]))

    equivalences.sort()
    implications.sort()
    contradictions.sort()

    results = {
        "equivalent": equivalences,
        "implies": implications,
        "contradicts": contradictions,
    }

    # Write JSON output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Write SQLite output
    write_sqlite_results("/app/results.db", equivalences, implications, contradictions)

    print(
        f"Results: {len(equivalences)} equivalences, "
        f"{len(implications)} implications, "
        f"{len(contradictions)} contradictions"
    )


if __name__ == "__main__":
    main()

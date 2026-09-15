#!/usr/bin/env python3
"""Medication reconciliation pipeline using RxNav REST API."""

import json
import sys
import time
from collections import defaultdict

import requests

RXNAV_BASE = "https://rxnav.nlm.nih.gov/REST"
RXCLASS_BASE = "https://rxnav.nlm.nih.gov/REST/rxclass"

_last_call = 0.0
MIN_INTERVAL = 0.35


def api_get(url, params=None, retries=7):
    """GET with rate-limiting, retry, and exponential backoff."""
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=45)
            _last_call = time.time()
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  API error after {retries} retries: {exc}",
                      file=sys.stderr)
                return {}
    return {}


def health_check():
    """Verify API is reachable before starting the pipeline."""
    for attempt in range(5):
        try:
            resp = requests.get(f"{RXNAV_BASE}/version.json", timeout=15)
            if resp.status_code == 200:
                ver = resp.json()
                print(f"RxNav API version: {ver}", file=sys.stderr)
                return True
        except Exception:
            pass
        time.sleep(2 ** attempt)
    print("WARNING: RxNav API health check failed", file=sys.stderr)
    return False


# ── Resolution helpers ────────────────────────────────────────────────────────


def resolve_ndc(ndc):
    """NDC -> RxCUI via rxcui.json with idtype=NDC."""
    data = api_get(f"{RXNAV_BASE}/rxcui.json",
                   {"idtype": "NDC", "id": ndc})
    ids = data.get("idGroup", {}).get("rxnormId", [])
    if ids:
        return ids[0]

    # Normalize to 11-digit format (5-4-2 segments)
    parts = ndc.split("-")
    if len(parts) == 3:
        ndc11 = parts[0].zfill(5) + parts[1].zfill(4) + parts[2].zfill(2)
        data = api_get(f"{RXNAV_BASE}/rxcui.json",
                       {"idtype": "NDC", "id": ndc11})
        ids = data.get("idGroup", {}).get("rxnormId", [])
        if ids:
            return ids[0]

    return None


def resolve_name(name):
    """Drug name -> RxCUI. Tries exact match, then broader search."""
    data = api_get(f"{RXNAV_BASE}/rxcui.json", {"name": name})
    ids = data.get("idGroup", {}).get("rxnormId", [])
    if ids:
        if len(ids) == 1:
            return ids[0]
        best = _pick_best_rxcui(ids, name)
        if best:
            return best
        return ids[0]

    # Try with allsrc=1
    data = api_get(f"{RXNAV_BASE}/rxcui.json",
                   {"name": name, "allsrc": 1})
    ids = data.get("idGroup", {}).get("rxnormId", [])
    if ids:
        if len(ids) == 1:
            return ids[0]
        best = _pick_best_rxcui(ids, name)
        if best:
            return best
        return ids[0]

    # getDrugs for brand-name lookup
    data = api_get(f"{RXNAV_BASE}/drugs.json", {"name": name})
    groups = data.get("drugGroup", {}).get("conceptGroup", [])
    name_lower = name.lower()
    for grp in groups:
        for prop in grp.get("conceptProperties", []):
            syn = prop.get("synonym", "").lower()
            cname = prop.get("name", "").lower()
            if name_lower == syn or name_lower == cname:
                return prop["rxcui"]
    for grp in groups:
        if grp.get("tty") in ("SBD", "SCD"):
            props = grp.get("conceptProperties", [])
            if props:
                return props[0]["rxcui"]

    # Fall back to approximate
    return resolve_approximate(name)


def _pick_best_rxcui(rxcui_list, query_name):
    """Given multiple RxCUI candidates, pick the one whose canonical name
    best matches the query string."""
    query_lower = query_name.lower().strip()

    # Pass 1: exact name or synonym match
    for rxcui in rxcui_list:
        props = get_properties(rxcui)
        cname = props.get("name", "").lower().strip()
        synonym = props.get("synonym", "").lower().strip()
        if cname == query_lower or synonym == query_lower:
            return rxcui

    # Pass 2: pick shortest name that contains the query
    scored = []
    for rxcui in rxcui_list:
        props = get_properties(rxcui)
        cname = props.get("name", "")
        scored.append((rxcui, cname))

    scored.sort(key=lambda x: len(x[1]))
    for rxcui, cname in scored:
        if cname and query_lower in cname.lower():
            return rxcui

    # Pass 3: pick the one whose name is most similar (shortest edit distance)
    for rxcui, cname in scored:
        if cname:
            return rxcui

    return None


def resolve_approximate(term):
    """Fuzzy term -> RxCUI via approximateTerm."""
    data = api_get(f"{RXNAV_BASE}/approximateTerm.json",
                   {"term": term, "maxEntries": 5})
    candidates = data.get("approximateGroup", {}).get("candidate", [])
    if candidates:
        return candidates[0].get("rxcui")
    return None


# ── Concept property / relationship helpers ──────────────────────────────────


_props_cache = {}


def get_properties(rxcui):
    if rxcui in _props_cache:
        return _props_cache[rxcui]
    data = api_get(f"{RXNAV_BASE}/rxcui/{rxcui}/properties.json")
    result = data.get("properties", {})
    _props_cache[rxcui] = result
    return result


_ingredients_cache = {}


def get_ingredients(rxcui):
    """Return base ingredients (TTY=IN) for a drug concept."""
    if rxcui in _ingredients_cache:
        return _ingredients_cache[rxcui]

    for attempt in range(3):
        data = api_get(f"{RXNAV_BASE}/rxcui/{rxcui}/allrelated.json")
        groups = (data.get("allRelatedGroup", {})
                      .get("conceptGroup", []))
        ingredients = []
        for grp in groups:
            if grp.get("tty") == "IN":
                for prop in grp.get("conceptProperties", []):
                    ingredients.append({
                        "rxcui": prop["rxcui"],
                        "name": prop["name"],
                    })
        if ingredients:
            # Sort by rxcui for deterministic ordering
            ingredients.sort(key=lambda x: x["rxcui"])
            _ingredients_cache[rxcui] = ingredients
            return ingredients
        if attempt < 2:
            time.sleep(1)

    _ingredients_cache[rxcui] = []
    return []


def get_generic_equivalent(rxcui, tty):
    """For SBD concepts, find the generic SCD via tradename_of."""
    if tty != "SBD":
        return None

    data = api_get(f"{RXNAV_BASE}/rxcui/{rxcui}/related.json",
                   {"rela": "tradename_of"})
    groups = data.get("relatedGroup", {}).get("conceptGroup", [])
    for grp in groups:
        if grp.get("tty") in ("SCD", "GPCK"):
            props = grp.get("conceptProperties", [])
            if props:
                return {"rxcui": props[0]["rxcui"],
                        "name": props[0]["name"]}

    # Fallback: use getGenericProduct
    data = api_get(f"{RXNAV_BASE}/rxcui/{rxcui}/generic.json")
    concepts = (data.get("minConceptGroup", {})
                    .get("minConcept", []))
    if concepts:
        return {"rxcui": concepts[0]["rxcui"],
                "name": concepts[0]["name"]}

    # Fallback: allrelated -> first SCD
    data = api_get(f"{RXNAV_BASE}/rxcui/{rxcui}/allrelated.json")
    groups = (data.get("allRelatedGroup", {})
                  .get("conceptGroup", []))
    for grp in groups:
        if grp.get("tty") == "SCD":
            props = grp.get("conceptProperties", [])
            if props:
                return {"rxcui": props[0]["rxcui"],
                        "name": props[0]["name"]}
    return None


def get_atc_classes(ingredient_rxcui):
    """ATC classification for a single ingredient RxCUI."""
    for attempt in range(3):
        data = api_get(f"{RXCLASS_BASE}/class/byRxcui.json",
                       {"rxcui": ingredient_rxcui, "relaSource": "ATC"})
        info_list = (data.get("rxclassDrugInfoList", {})
                         .get("rxclassDrugInfo", []))

        classes = []
        seen = set()
        for info in info_list:
            ci = info.get("rxclassMinConceptItem", {})
            class_id = ci.get("classId", "")
            class_name = ci.get("className", "")
            if class_id and class_name:
                key = (class_id, class_name)
                if key not in seen:
                    seen.add(key)
                    classes.append({
                        "class_id": class_id,
                        "class_name": class_name,
                    })
        if classes:
            return classes
        if attempt < 2:
            time.sleep(1)
    return []


# ── Formulary helpers ────────────────────────────────────────────────────────


def build_formulary_ingredient_index(formulary_items):
    """Build a map from ingredient RxCUI to formulary items."""
    index = defaultdict(list)
    for f_item in formulary_items:
        f_rxcui = f_item["rxcui"]
        ings = get_ingredients(f_rxcui)
        for ing in ings:
            index[ing["rxcui"]].append(f_item)
    return dict(index)


def find_formulary_alternatives(med_rxcui, med_ingredients,
                                formulary_by_ingredient):
    """For a non-formulary medication, find formulary items sharing ingredients."""
    alternatives = {}
    for ing in med_ingredients:
        for f_item in formulary_by_ingredient.get(ing["rxcui"], []):
            if f_item["rxcui"] != med_rxcui and f_item["rxcui"] not in alternatives:
                alternatives[f_item["rxcui"]] = {
                    "rxcui": f_item["rxcui"],
                    "name": f_item["name"],
                }
    # Sort by rxcui for deterministic output
    return sorted(alternatives.values(), key=lambda x: x["rxcui"])


# ── Main pipeline ────────────────────────────────────────────────────────────


def main():
    health_check()

    with open("/app/medications.json") as fh:
        input_data = json.load(fh)
    with open("/app/formulary.json") as fh:
        formulary_data = json.load(fh)

    patient_id = input_data["patient_id"]
    medications = input_data["medications"]

    # Build formulary indexes
    formulary_items = formulary_data["preferred_medications"]
    formulary_rxcuis = {m["rxcui"] for m in formulary_items}
    print("Building formulary ingredient index...", file=sys.stderr)
    formulary_by_ingredient = build_formulary_ingredient_index(formulary_items)
    print(f"  Indexed {len(formulary_by_ingredient)} ingredients across "
          f"{len(formulary_items)} formulary items", file=sys.stderr)

    report_meds = []
    ing_tracker = defaultdict(lambda: {"name": "", "meds": []})

    for med in medications:
        mid = med["id"]
        mtype = med["type"]
        mval = med["value"]
        print(f"[{mid}] resolving ({mtype}): {mval}")

        # ── Resolve to RxCUI ──
        rxcui = None
        if mtype == "ndc":
            rxcui = resolve_ndc(mval)
        elif mtype == "drug_name":
            rxcui = resolve_name(mval)
        elif mtype == "approximate":
            rxcui = resolve_approximate(mval)

        if not rxcui:
            print(f"  !! could not resolve {mid}", file=sys.stderr)
            report_meds.append({
                "id": mid, "rxcui": "", "name": "", "tty": "",
                "ingredients": [], "generic_equivalent": None,
                "atc_classes": [], "on_formulary": False,
                "formulary_alternatives": [],
            })
            continue

        # ── Concept properties ──
        props = get_properties(rxcui)
        name = props.get("name", "")
        tty = props.get("tty", "")
        print(f"  -> RxCUI {rxcui}  TTY={tty}  {name}")

        # ── Base ingredients (IN) ──
        ingredients = get_ingredients(rxcui)
        print(f"  ingredients: {[i['name'] for i in ingredients]}")

        # ── Generic equivalent (SBD->SCD) ──
        generic_eq = get_generic_equivalent(rxcui, tty)

        # ── ATC classes per ingredient ──
        atc_classes = []
        seen_atc = set()
        for ing in ingredients:
            for c in get_atc_classes(ing["rxcui"]):
                key = (c["class_id"], c["class_name"])
                if key not in seen_atc:
                    seen_atc.add(key)
                    atc_classes.append(c)

        # ── Formulary check ──
        on_formulary = str(rxcui) in formulary_rxcuis
        formulary_alternatives = []
        if not on_formulary:
            formulary_alternatives = find_formulary_alternatives(
                str(rxcui), ingredients, formulary_by_ingredient,
            )

        # ── Track ingredients for duplication detection ──
        for ing in ingredients:
            ing_tracker[ing["rxcui"]]["name"] = ing["name"]
            ing_tracker[ing["rxcui"]]["meds"].append(mid)

        report_meds.append({
            "id": mid,
            "rxcui": str(rxcui),
            "name": name,
            "tty": tty,
            "ingredients": ingredients,
            "generic_equivalent": generic_eq,
            "atc_classes": atc_classes,
            "on_formulary": on_formulary,
            "formulary_alternatives": formulary_alternatives,
        })

    # ── Therapeutic duplications ──
    duplications = []
    for irxcui, info in sorted(ing_tracker.items()):
        if len(info["meds"]) >= 2:
            duplications.append({
                "ingredient_rxcui": str(irxcui),
                "ingredient_name": info["name"],
                "medication_ids": sorted(info["meds"]),
            })

    report = {
        "patient_id": patient_id,
        "medications": report_meds,
        "therapeutic_duplications": duplications,
    }

    with open("/app/reconciliation_report.json", "w") as fh:
        json.dump(report, fh, indent=2)

    print(f"\nDone. {len(report_meds)} medications processed, "
          f"{len(duplications)} duplication group(s) detected.")


if __name__ == "__main__":
    main()

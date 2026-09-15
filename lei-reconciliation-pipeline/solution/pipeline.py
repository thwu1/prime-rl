#!/usr/bin/env python3

"""
GLEIF LEI Forensic Compliance Assessment Pipeline.

Validates LEI checksums per ISO 17442 MOD 97-10, retrieves entity data and
relationship metadata from the GLEIF API (including conformity flags,
corroboration levels, and reporting exceptions), builds a cross-border
ownership topology, detects metadata drift, and produces a composite
risk classification report.
"""

import json
import os
import time

import requests

PORTFOLIO_PATH = "/app/data/portfolio.json"
OUTPUT_DIR = "/app/output"
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "report.json")
API_BASE = "https://api.gleif.org/api/v1"
HEADERS = {"Accept": "application/vnd.api+json"}
DELAY = 0.3


# ─── LEI checksum validation (ISO 17442 MOD 97-10) ───────────────────────────

def validate_lei(lei):
    """Returns (is_valid, reason)."""
    if len(lei) != 20:
        return False, "wrong_length"
    if not lei.isalnum():
        return False, "invalid_characters"
    digits = ""
    for c in lei.upper():
        digits += c if c.isdigit() else str(ord(c) - 55)
    if int(digits) % 97 != 1:
        return False, "checksum_failed"
    return True, "valid"


# ─── GLEIF API helpers ────────────────────────────────────────────────────────

def api_get(url, session, retries=3):
    """GET with retries, rate-limit handling, and 404 tolerance."""
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.RequestException:
            time.sleep(1)
    return None


def extract_assessment(resp):
    """Extract registry assessment fields from a lei-records response."""
    if not resp or "data" not in resp:
        return _empty_assessment()
    d = resp["data"]
    a = d.get("attributes", {})
    e = a.get("entity", {})
    r = a.get("registration", {})
    return {
        "legal_name": e.get("legalName", {}).get("name", ""),
        "country": e.get("legalAddress", {}).get("country", ""),
        "jurisdiction": e.get("jurisdiction", ""),
        "registration_status": r.get("status", ""),
        "conformity_flag": a.get("conformityFlag", ""),
        "corroboration_level": r.get("corroborationLevel", ""),
        "managing_lou": r.get("managingLou", ""),
        "bic": a.get("bic") or [],
        "relationship_registration_status": None,
    }


def _empty_assessment():
    return {
        "legal_name": "", "country": "", "jurisdiction": "",
        "registration_status": "", "conformity_flag": "",
        "corroboration_level": "", "managing_lou": "",
        "bic": [], "relationship_registration_status": None,
    }


# ─── Parent / reporting-exception discovery ───────────────────────────────────

def get_parent_info(resp, session):
    """
    Inspect the entity's relationships.direct-parent.links to determine
    whether it has a parent relationship or a reporting exception.

    Returns (type, data, rel_status) where:
      type = "exception" | "parent" | "none"
      data = exception dict | parent LEI string | None
      rel_status = relationship registration status | None
    """
    if not resp or "data" not in resp:
        return "none", None, None
    rels = resp["data"].get("relationships", {})
    dp = rels.get("direct-parent", {}).get("links", {})

    if "reporting-exception" in dp:
        exc_url = dp["reporting-exception"]
        exc_resp = api_get(exc_url, session)
        exc = _extract_exception(exc_resp)
        return "exception", exc, None
    elif "relationship-record" in dp:
        rel_url = dp["relationship-record"]
        rel_resp = api_get(rel_url, session)
        parent_lei, rel_status = _extract_parent_rel(rel_resp)
        return "parent", parent_lei, rel_status

    return "none", None, None


def _extract_exception(resp):
    if not resp:
        return {"exception_category": "UNKNOWN", "exception_reason": "UNKNOWN"}
    d = resp.get("data", {})
    if isinstance(d, list):
        d = d[0] if d else {}
    a = d.get("attributes", {})
    return {
        "exception_category": a.get("category", "UNKNOWN"),
        "exception_reason": a.get("reason", "UNKNOWN"),
    }


def _extract_parent_rel(resp):
    if not resp:
        return None, None
    d = resp.get("data", {})
    if isinstance(d, list):
        d = d[0] if d else {}
    a = d.get("attributes", {})
    rel = a.get("relationship", {})
    parent_lei = rel.get("endNode", {}).get("id", "")
    rel_status = a.get("registration", {}).get("status", "")
    return parent_lei, rel_status


# ─── Ownership graph helpers ─────────────────────────────────────────────────

def trace_ultimate_parent(lei, parent_map, visited=None):
    if visited is None:
        visited = set()
    if lei in visited:
        return lei
    visited.add(lei)
    p = parent_map.get(lei)
    return trace_ultimate_parent(p, parent_map, visited) if p and p != lei else lei


def chain_depth(lei, parent_map, cache):
    if lei in cache:
        return cache[lei]
    p = parent_map.get(lei)
    if not p or p == lei:
        cache[lei] = 0
        return 0
    cache[lei] = 1 + chain_depth(p, parent_map, cache)
    return cache[lei]


# ─── Main pipeline ────────────────────────────────────────────────────────────

def main():
    with open(PORTFOLIO_PATH) as f:
        portfolio = json.load(f)
    print(f"Portfolio: {len(portfolio)} entities")

    # ── Phase 1: Checksum validation ──────────────────────────────────────
    valid_leis, invalid_leis = [], []
    for entry in portfolio:
        lei = entry["lei"]
        ok, reason = validate_lei(lei)
        if ok:
            valid_leis.append(lei)
        else:
            invalid_leis.append({"lei": lei, "reason": reason})
    print(f"Checksums: {len(valid_leis)} valid, {len(invalid_leis)} invalid")

    # ── Phase 2: Registry assessment + parent/exception discovery ─────────
    session = requests.Session()
    entities = {}
    parent_map = {}
    reporting_exceptions = {}

    for i, lei in enumerate(valid_leis):
        print(f"  [{i+1}/{len(valid_leis)}] {lei}")

        resp = api_get(f"{API_BASE}/lei-records/{lei}", session)
        entities[lei] = extract_assessment(resp)
        time.sleep(DELAY)

        ptype, pdata, rstat = get_parent_info(resp, session)
        if ptype == "exception":
            reporting_exceptions[lei] = pdata
        elif ptype == "parent" and pdata:
            parent_map[lei] = pdata
            entities[lei]["relationship_registration_status"] = rstat
            print(f"    -> parent {pdata} (rel: {rstat})")
        time.sleep(DELAY)

    print(f"Registry: {len(entities)} entities, {len(parent_map)} parent links, "
          f"{len(reporting_exceptions)} exceptions")

    # ── Phase 3: Ownership topology ───────────────────────────────────────
    groups = {}
    for lei in valid_leis:
        up = trace_ultimate_parent(lei, parent_map)
        groups.setdefault(up, []).append(lei)

    conglomerates = []
    standalone = []

    for parent_lei, members in groups.items():
        subs = [m for m in members if m != parent_lei]
        if subs:
            # Jurisdictions spanned across the group
            jurisdictions = set()
            parent_jurisdiction = entities.get(parent_lei, {}).get("jurisdiction", "")
            parent_country = entities.get(parent_lei, {}).get("country", "")
            if parent_jurisdiction:
                jurisdictions.add(parent_jurisdiction)

            cross_border = 0
            for s in subs:
                sj = entities.get(s, {}).get("jurisdiction", "")
                sc = entities.get(s, {}).get("country", "")
                if sj:
                    jurisdictions.add(sj)
                # Cross-border: compare child's country with its direct parent's country
                direct_parent = parent_map.get(s, parent_lei)
                dp_country = entities.get(direct_parent, {}).get("country", "")
                if sc and dp_country and sc != dp_country:
                    cross_border += 1

            conglomerates.append({
                "ultimate_parent_lei": parent_lei,
                "ultimate_parent_name": entities.get(parent_lei, {}).get("legal_name", ""),
                "subsidiaries": subs,
                "subsidiary_count": len(subs),
                "jurisdictions_spanned": sorted(jurisdictions),
                "cross_border_links": cross_border,
            })
        else:
            standalone.append(parent_lei)

    depth_cache = {}
    max_depth = max(
        (chain_depth(lei, parent_map, depth_cache) for lei in valid_leis),
        default=0,
    )

    print(f"Topology: {len(conglomerates)} conglomerates, "
          f"{len(standalone)} standalone, max depth {max_depth}")

    # ── Phase 4: Metadata discrepancies ───────────────────────────────────
    portfolio_by_lei = {e["lei"]: e for e in portfolio}
    discrepancies = []

    for lei in valid_leis:
        if lei not in entities or lei not in portfolio_by_lei:
            continue
        local = portfolio_by_lei[lei]
        api = entities[lei]

        ln = local.get("local_name", "").strip()
        an = api.get("legal_name", "").strip()
        if ln and an and ln.lower() != an.lower():
            discrepancies.append({
                "lei": lei, "field": "name",
                "local_value": ln, "registry_value": an,
            })

        lc = local.get("local_country", "").strip()
        ac = api.get("country", "").strip()
        if lc and ac and lc.upper() != ac.upper():
            discrepancies.append({
                "lei": lei, "field": "country",
                "local_value": lc, "registry_value": ac,
            })

        lj = local.get("local_jurisdiction", "").strip()
        aj = api.get("jurisdiction", "").strip()
        if lj and aj and lj.upper() != aj.upper():
            discrepancies.append({
                "lei": lei, "field": "jurisdiction",
                "local_value": lj, "registry_value": aj,
            })

    print(f"Discrepancies: {len(discrepancies)} found")
    for d in discrepancies:
        print(f"  {d['lei']}: {d['field']} "
              f"'{d['local_value']}' vs '{d['registry_value']}'")

    # ── Phase 5: Risk classification ──────────────────────────────────────
    disc_leis = set(d["lei"] for d in discrepancies)
    classifications = {}

    for lei in valid_leis:
        e = entities[lei]
        factors = []

        rs = e.get("registration_status", "")
        if rs and rs != "ISSUED":
            factors.append("registration_degraded")

        cf = e.get("conformity_flag", "")
        if cf and cf != "CONFORMING":
            factors.append("non_conforming")

        cl = e.get("corroboration_level", "")
        if cl and cl != "FULLY_CORROBORATED":
            factors.append("weak_corroboration")

        rrs = e.get("relationship_registration_status")
        if rrs == "LAPSED":
            factors.append("stale_relationship")

        if lei in disc_leis:
            factors.append("metadata_drift")

        n = len(factors)
        tier = "HIGH" if n >= 3 else ("MEDIUM" if n >= 1 else "LOW")
        classifications[lei] = {"risk_tier": tier, "risk_factors": factors}

    hi = sum(1 for c in classifications.values() if c["risk_tier"] == "HIGH")
    me = sum(1 for c in classifications.values() if c["risk_tier"] == "MEDIUM")
    lo = sum(1 for c in classifications.values() if c["risk_tier"] == "LOW")
    print(f"Risk: {hi} HIGH, {me} MEDIUM, {lo} LOW")

    # ── Phase 6: Assemble report ──────────────────────────────────────────
    report = {
        "checksum_validation": {
            "valid_leis": valid_leis,
            "invalid_leis": invalid_leis,
        },
        "registry_assessment": {
            "entities": entities,
        },
        "ownership_topology": {
            "conglomerates": conglomerates,
            "standalone_entities": standalone,
            "reporting_exceptions": reporting_exceptions,
            "max_depth": max_depth,
        },
        "metadata_discrepancies": {
            "discrepancies": discrepancies,
        },
        "risk_classification": {
            "classifications": classifications,
        },
        "summary": {
            "total_entities": len(portfolio),
            "valid_checksums": len(valid_leis),
            "invalid_checksums": len(invalid_leis),
            "conglomerate_count": len(conglomerates),
            "discrepancy_count": len(discrepancies),
            "high_risk_count": hi,
            "medium_risk_count": me,
            "low_risk_count": lo,
        },
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

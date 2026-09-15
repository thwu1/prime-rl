#!/usr/bin/env python3
"""

GLEIF Ownership Chain Forensics — Solution

Resolves heterogeneous identifiers (LEI/BIC/name) to canonical GLEIF records,
builds verified parent chains, assesses relationship quality, and produces
a forensic ownership report.
"""

import json
import os
import time

import requests

BASE_URL = "https://api.gleif.org/api/v1"
HEADERS = {"Accept": "application/vnd.api+json"}
RETRY_DELAY = 2
MAX_RETRIES = 3


# --------------- API helpers ---------------

def api_get(url, params=None):
    """GET with retries and rate-limit handling."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            return None
        except requests.RequestException:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    return None


def get_pagination_total(url):
    """Extract total count from paginated endpoint metadata."""
    data = api_get(url, params={"page[size]": 1, "page[number]": 1})
    if data is None:
        return 0
    return data.get("meta", {}).get("pagination", {}).get("total", 0)


# --------------- LEI checksum (ISO 17442 MOD 97-10) ---------------

def validate_lei_checksum(lei):
    """Validate an LEI code using the ISO 17442 MOD 97-10 algorithm."""
    if len(lei) != 20:
        return False
    if not lei.isalnum():
        return False
    if not lei[18:20].isdigit():
        return False
    numeric_str = ""
    for ch in lei.upper():
        if ch.isdigit():
            numeric_str += ch
        else:
            numeric_str += str(ord(ch) - ord("A") + 10)
    return int(numeric_str) % 97 == 1


# --------------- Identifier resolution ---------------

def resolve_by_lei(lei):
    """Fetch entity record by LEI."""
    data = api_get(f"{BASE_URL}/lei-records/{lei}")
    if data and "data" in data:
        return data["data"]
    return None


def resolve_by_bic(bic):
    """Resolve a BIC code to an entity record via filter endpoint."""
    data = api_get(
        f"{BASE_URL}/lei-records",
        params={"filter[bic]": bic, "page[size]": 1},
    )
    if data and "data" in data and len(data["data"]) > 0:
        return data["data"][0]
    return None


def _pick_best_name_match(records, target_name):
    """From a list of GLEIF records, pick the one whose legal name best matches target."""
    target_upper = target_name.upper()
    # Prefer exact case-insensitive match on legal name
    for rec in records:
        legal_name = rec["attributes"]["entity"]["legalName"]["name"]
        if legal_name.upper() == target_upper:
            return rec
    # Fall back to first result
    return records[0] if records else None


def resolve_by_name(name):
    """Resolve an entity name to a GLEIF record.

    Uses exact legal-name filter first (filter[entity.legalName]) for precise
    matching, then falls back to fulltext search with best-match ranking.
    """
    # Try exact legal name filter first
    data = api_get(
        f"{BASE_URL}/lei-records",
        params={"filter[entity.legalName]": name, "page[size]": 10},
    )
    if data and "data" in data and len(data["data"]) > 0:
        match = _pick_best_name_match(data["data"], name)
        if match:
            return match

    # Fallback: fulltext search with best-match selection
    data = api_get(
        f"{BASE_URL}/lei-records",
        params={"filter[fulltext]": name, "page[size]": 10},
    )
    if data and "data" in data and len(data["data"]) > 0:
        match = _pick_best_name_match(data["data"], name)
        if match:
            return match

    return None


# --------------- Relationship traversal ---------------

def _extract_from_relationship_record(rec):
    """Extract (parent_lei, corroboration, reg_status) from a relationship record."""
    if rec is None:
        return None, None, None
    if isinstance(rec, list):
        rec = rec[0] if rec else None
    if not isinstance(rec, dict):
        return None, None, None
    attrs = rec.get("attributes", {})
    # Relationship-type record
    if "relationship" in attrs:
        rel = attrs["relationship"]
        reg = attrs.get("registration", {})
        parent_lei = rel.get("endNode", {}).get("id")
        return parent_lei, reg.get("corroborationLevel"), reg.get("status")
    # Entity-type record (fallback)
    parent_lei = attrs.get("lei") or rec.get("id")
    return parent_lei, None, None


def get_direct_parent_info(lei):
    """Get (parent_lei, corroboration_level, registration_status) for direct parent.

    Tries the relationship endpoint first (has corroboration metadata),
    then falls back to the entity endpoint.
    """
    # Try relationship endpoint
    data = api_get(f"{BASE_URL}/lei-records/{lei}/direct-parent-relationship")
    if data is not None and "data" in data and data["data"] is not None:
        parent_lei, corr, status = _extract_from_relationship_record(data["data"])
        if parent_lei:
            return parent_lei, corr, status

    # Fallback to entity endpoint
    data = api_get(f"{BASE_URL}/lei-records/{lei}/direct-parent")
    if data is not None and "data" in data and data["data"] is not None:
        rec = data["data"]
        if isinstance(rec, list):
            rec = rec[0] if rec else None
        if isinstance(rec, dict):
            parent_lei = rec.get("attributes", {}).get("lei") or rec.get("id")
            if parent_lei:
                return parent_lei, None, None

    return None, None, None


def get_ultimate_parent_lei(lei):
    """Get the claimed ultimate parent LEI."""
    # Try relationship endpoint
    data = api_get(f"{BASE_URL}/lei-records/{lei}/ultimate-parent-relationship")
    if data is not None and "data" in data and data["data"] is not None:
        parent_lei, _, _ = _extract_from_relationship_record(data["data"])
        if parent_lei:
            return parent_lei

    # Fallback to entity endpoint
    data = api_get(f"{BASE_URL}/lei-records/{lei}/ultimate-parent")
    if data is not None and "data" in data and data["data"] is not None:
        rec = data["data"]
        if isinstance(rec, list):
            rec = rec[0] if rec else None
        if isinstance(rec, dict):
            parent_lei = rec.get("attributes", {}).get("lei") or rec.get("id")
            if parent_lei:
                return parent_lei

    return lei  # Self is ultimate parent if no data


def build_parent_chain(lei):
    """Recursively follow direct-parent links to build the full chain.

    Returns:
        chain: ordered list of LEIs [direct_parent, grandparent, ..., root]
        quality: list of dicts with corroboration_level and registration_status
                 for each link in the chain
    """
    chain = []
    quality = []
    current = lei
    visited = {lei}

    while True:
        parent_lei, corr, reg_status = get_direct_parent_info(current)
        if parent_lei is None or parent_lei == current:
            break
        if parent_lei in visited:
            break  # Cycle detection
        visited.add(parent_lei)
        chain.append(parent_lei)
        quality.append({
            "corroboration_level": corr,
            "registration_status": reg_status,
        })
        current = parent_lei
        time.sleep(0.2)

    return chain, quality


# --------------- Reporting exceptions ---------------

def get_reporting_exceptions(lei):
    """Check for reporting exceptions on an entity."""
    data = api_get(f"{BASE_URL}/lei-records/{lei}/reporting-exceptions")
    if data is not None and "data" in data:
        exceptions = data["data"]
        if isinstance(exceptions, list) and len(exceptions) > 0:
            exc = exceptions[0]
            attrs = exc.get("attributes", {})
            reason = (
                attrs.get("reason")
                or attrs.get("exceptionReason")
                or attrs.get("category")
                or attrs.get("exceptionCategory")
            )
            return True, reason
    return False, None


# --------------- Entity attribute extraction ---------------

def extract_entity_attrs(record):
    """Extract key attributes from a GLEIF entity record."""
    attrs = record["attributes"]
    entity = attrs["entity"]
    reg = attrs["registration"]
    return {
        "entity_name": entity["legalName"]["name"],
        "jurisdiction": entity.get("jurisdiction"),
        "entity_status": entity.get("status"),
        "registration_status": reg.get("status"),
        "conformity_flag": attrs.get("conformityFlag"),
        "bic_codes": attrs.get("bic") or [],
    }


# --------------- Main pipeline ---------------

def process_entry(entry):
    """Process a single portfolio entry and return its forensic record."""
    eid = entry["id"]
    identifier = entry["identifier"]
    etype = entry["type"]

    print(f"  [{eid}] Resolving {etype}: {identifier}")

    result = {
        "id": eid,
        "input_identifier": identifier,
        "input_type": etype,
        "resolved_lei": None,
        "resolution_method": None,
        "checksum_valid": None,
        "entity_name": None,
        "jurisdiction": None,
        "entity_status": None,
        "registration_status": None,
        "conformity_flag": None,
        "bic_codes": [],
        "isin_count": 0,
        "direct_children_count": 0,
        "parent_chain": [],
        "chain_depth": 0,
        "claimed_ultimate_parent_lei": None,
        "chain_consistent": None,
        "has_reporting_exception": False,
        "exception_reason": None,
        "relationship_registration_status": None,
        "corroboration_level": None,
    }

    # ---- Identifier resolution ----
    entity_record = None

    if etype == "lei":
        valid = validate_lei_checksum(identifier)
        result["checksum_valid"] = valid
        if not valid:
            result["resolution_method"] = "invalid"
            return result, False
        entity_record = resolve_by_lei(identifier)
        if entity_record:
            result["resolved_lei"] = identifier
            result["resolution_method"] = "checksum_validated"
        else:
            result["resolution_method"] = "invalid"
            return result, False

    elif etype == "bic":
        entity_record = resolve_by_bic(identifier)
        if entity_record:
            result["resolved_lei"] = entity_record["attributes"]["lei"]
            result["resolution_method"] = "bic_lookup"
        else:
            result["resolution_method"] = "invalid"
            return result, False

    elif etype == "name":
        entity_record = resolve_by_name(identifier)
        if entity_record:
            result["resolved_lei"] = entity_record["attributes"]["lei"]
            result["resolution_method"] = "fulltext_search"
        else:
            result["resolution_method"] = "invalid"
            return result, False

    # ---- Entity attributes ----
    if entity_record:
        attrs = extract_entity_attrs(entity_record)
        result.update(attrs)

    lei = result["resolved_lei"]
    print(f"        -> Resolved to {lei} ({result['entity_name']})")

    # ---- Parent chain ----
    print(f"        -> Building parent chain...")
    chain, quality = build_parent_chain(lei)
    result["parent_chain"] = chain
    result["chain_depth"] = len(chain)

    if quality:
        result["corroboration_level"] = quality[0]["corroboration_level"]
        result["relationship_registration_status"] = quality[0]["registration_status"]

    # ---- Ultimate parent & chain consistency ----
    claimed_ultimate = get_ultimate_parent_lei(lei)
    result["claimed_ultimate_parent_lei"] = claimed_ultimate

    if len(chain) == 0:
        # Top-level: consistent if claimed ultimate is self
        result["chain_consistent"] = (
            claimed_ultimate == lei or claimed_ultimate is None
        )
    else:
        # Chain terminal should match claimed ultimate parent
        chain_terminal = chain[-1]
        result["chain_consistent"] = (chain_terminal == claimed_ultimate)

    # ---- Reporting exceptions (parentless entities only) ----
    if len(chain) == 0:
        has_exc, reason = get_reporting_exceptions(lei)
        result["has_reporting_exception"] = has_exc
        result["exception_reason"] = reason

    # ---- Count metrics ----
    print(f"        -> Fetching ISIN and subsidiary counts...")
    result["isin_count"] = get_pagination_total(
        f"{BASE_URL}/lei-records/{lei}/isins"
    )
    result["direct_children_count"] = get_pagination_total(
        f"{BASE_URL}/lei-records/{lei}/direct-child-relationships"
    )

    print(
        f"        -> chain_depth={result['chain_depth']}, "
        f"isins={result['isin_count']}, children={result['direct_children_count']}"
    )

    time.sleep(0.3)
    return result, True


def main():
    with open("/app/data/portfolio.json") as f:
        portfolio = json.load(f)

    print(f"Processing {len(portfolio)} portfolio entries...\n")

    entities = []
    unresolved = []

    for entry in portfolio:
        result, resolved = process_entry(entry)
        entities.append(result)
        if not resolved:
            unresolved.append(result["id"])

    # ---- Build ownership clusters ----
    print("\nBuilding ownership clusters...")
    clusters_raw = {}
    for ent in entities:
        if ent["resolved_lei"] is None:
            continue
        ult = ent["claimed_ultimate_parent_lei"]
        if ult is None:
            ult = ent["resolved_lei"]
        if ult not in clusters_raw:
            clusters_raw[ult] = {
                "member_ids": [],
                "member_leis": [],
                "jurisdictions": set(),
                "max_chain_depth": 0,
                "total_isin_exposure": 0,
                "total_direct_children": 0,
                "corr_scores": [],
            }
        c = clusters_raw[ult]
        c["member_ids"].append(ent["id"])
        c["member_leis"].append(ent["resolved_lei"])
        if ent["jurisdiction"]:
            c["jurisdictions"].add(ent["jurisdiction"])
        c["max_chain_depth"] = max(c["max_chain_depth"], ent["chain_depth"])
        c["total_isin_exposure"] += ent["isin_count"]
        c["total_direct_children"] += ent["direct_children_count"]

        # Collect corroboration scores for DQS
        if ent["corroboration_level"]:
            score_map = {
                "FULLY_CORROBORATED": 1.0,
                "PARTIALLY_CORROBORATED": 0.5,
                "ENTITY_SUPPLIED_ONLY": 0.0,
            }
            score = score_map.get(ent["corroboration_level"], 0.0)
            c["corr_scores"].append(score)

    clusters = {}
    for ult_lei, c in clusters_raw.items():
        scores = c["corr_scores"]
        dqs = (sum(scores) / len(scores)) if scores else None
        clusters[ult_lei] = {
            "member_ids": c["member_ids"],
            "member_leis": c["member_leis"],
            "jurisdictions": sorted(list(c["jurisdictions"])),
            "max_chain_depth": c["max_chain_depth"],
            "total_isin_exposure": c["total_isin_exposure"],
            "total_direct_children": c["total_direct_children"],
            "data_quality_score": dqs,
        }

    # ---- Summary ----
    resolved = [e for e in entities if e["resolved_lei"] is not None]
    summary = {
        "total_entries": len(portfolio),
        "resolved_count": len(resolved),
        "unresolved_count": len(unresolved),
        "cluster_count": len(clusters),
        "entities_with_parents": sum(
            1 for e in resolved if e["chain_depth"] > 0
        ),
        "total_chain_depth": sum(e["chain_depth"] for e in resolved),
        "total_isin_exposure": sum(e["isin_count"] for e in resolved),
        "total_direct_children": sum(
            e["direct_children_count"] for e in resolved
        ),
    }

    report = {
        "entities": entities,
        "clusters": clusters,
        "unresolved": unresolved,
        "summary": summary,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/forensics.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nForensics report written to /app/output/forensics.json")
    print(f"  Resolved: {summary['resolved_count']}/{summary['total_entries']}")
    print(f"  Unresolved: {summary['unresolved_count']}")
    print(f"  Clusters: {summary['cluster_count']}")
    print(f"  With parents: {summary['entities_with_parents']}")
    print(f"  Total ISINs: {summary['total_isin_exposure']}")
    print(f"  Total children: {summary['total_direct_children']}")


if __name__ == "__main__":
    main()

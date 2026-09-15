#!/usr/bin/env python3
"""
Federal Procurement Concentration Analysis Tool.

Queries the USAspending.gov REST API to produce a market concentration
report for specified NAICS codes and fiscal year.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import requests

API_BASE = "https://api.usaspending.gov/api/v2"

# Contract award type codes (exclude grants, loans, other assistance)
CONTRACT_AWARD_TYPES = ["A", "B", "C", "D"]


def fy_to_dates(fy: int):
    """Convert federal fiscal year to date range.

    FY starts October 1 of the prior calendar year and ends September 30.
    E.g. FY2023 = 2022-10-01 through 2023-09-30.
    """
    return f"{fy - 1}-10-01", f"{fy}-09-30"


def api_post(endpoint: str, payload: dict, retries: int = 4) -> dict:
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def api_get(endpoint: str, params: dict = None, retries: int = 4) -> dict:
    url = f"{API_BASE}/{endpoint}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=120)
            if resp.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def build_search_filters(naics_code: str, fy: int) -> dict:
    """Build the Advanced Search filter object for a NAICS code and FY."""
    start, end = fy_to_dates(fy)
    return {
        "time_period": [{"start_date": start, "end_date": end}],
        "award_type_codes": CONTRACT_AWARD_TYPES,
        "naics_codes": [naics_code],
    }


def extract_recipient_id(result: dict) -> str:
    """Extract recipient identifier from an API result, trying multiple field names."""
    for key in ("recipient_id", "id", "recipient_hash"):
        val = result.get(key)
        if val is not None and val != "":
            return str(val)
    return ""


def fetch_top_recipients(naics_code: str, fy: int, target_count: int = 50) -> list:
    """Fetch top recipients by contract spending for a NAICS code.

    Handles pagination to retrieve at least `target_count` recipients.
    """
    filters = build_search_filters(naics_code, fy)
    all_results = []
    page = 1
    per_page = min(target_count, 100)

    while len(all_results) < target_count:
        payload = {
            "filters": filters,
            "category": "recipient",
            "limit": per_page,
            "page": page,
            "subawards": False,
        }
        data = api_post("search/spending_by_category/recipient/", payload)
        page_results = data.get("results", [])
        if not page_results:
            break
        all_results.extend(page_results)
        has_next = data.get("page_metadata", {}).get("hasNext", False)
        if not has_next:
            break
        page += 1
        time.sleep(0.5)

    return all_results[:target_count]


def fetch_state_geography(naics_code: str, fy: int) -> list:
    """Fetch state-level geographic distribution of contract spending."""
    filters = build_search_filters(naics_code, fy)
    payload = {
        "scope": "place_of_performance",
        "geo_layer": "state",
        "filters": filters,
        "subawards": False,
    }
    data = api_post("search/spending_by_geography/", payload)
    return data.get("results", [])


def fetch_awarding_agencies(naics_code: str, fy: int) -> list:
    """Fetch the top awarding agencies for a NAICS code."""
    filters = build_search_filters(naics_code, fy)
    payload = {
        "filters": filters,
        "category": "awarding_agency",
        "limit": 10,
        "page": 1,
        "subawards": False,
    }
    data = api_post("search/spending_by_category/awarding_agency/", payload)
    return data.get("results", [])


def fetch_recipient_profile(recipient_hash: str, fy: int) -> dict:
    """Fetch detailed profile for a recipient by their hash identifier."""
    return api_get(f"recipient/{recipient_hash}/", params={"year": str(fy)})


def compute_hhi(amounts: list) -> float:
    """Herfindahl-Hirschman Index using percentage-point shares.

    HHI = sum(share_i^2) where share_i is in percentage points (0-100).
    Range: 0 (perfect competition) to 10000 (monopoly).
    """
    total = sum(amounts)
    if total <= 0:
        return 0.0
    shares_pct = [(a / total) * 100.0 for a in amounts]
    return sum(s * s for s in shares_pct)


def compute_cr(amounts: list, n: int) -> float:
    """Concentration ratio: % of total held by top-n firms."""
    total = sum(amounts)
    if total <= 0:
        return 0.0
    sorted_desc = sorted(amounts, reverse=True)
    top_n = sum(sorted_desc[:n])
    return (top_n / total) * 100.0


def safe_amount(val) -> float:
    """Safely extract a numeric amount, defaulting to 0."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def main():
    parser = argparse.ArgumentParser(
        description="Federal Procurement Concentration Analyzer"
    )
    parser.add_argument("--naics", nargs="+", required=True,
                        help="One or more 6-digit NAICS codes")
    parser.add_argument("--fy", type=int, required=True,
                        help="Federal fiscal year")
    parser.add_argument("--output", required=True,
                        help="Path for the JSON report output")
    args = parser.parse_args()

    report = {
        "metadata": {
            "naics_codes": args.naics,
            "fiscal_year": args.fy,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "per_naics": {},
        "cross_naics_overlap": [],
        "top_recipient_profile": {},
    }

    # Global tracking: recipient_id -> {name, naics: {code: amount}}
    global_recipients = {}
    # Track top recipient overall (by amount, not requiring a valid hash ID)
    overall_top_name = ""
    overall_top_id = ""
    overall_top_amount = 0.0

    for naics_code in args.naics:
        print(f"Processing NAICS {naics_code}...", file=sys.stderr)

        # ── Fetch data from API ──────────────────────────────────────
        recipients_raw = fetch_top_recipients(naics_code, args.fy)
        time.sleep(0.5)
        geo_raw = fetch_state_geography(naics_code, args.fy)
        time.sleep(0.5)
        agencies_raw = fetch_awarding_agencies(naics_code, args.fy)
        time.sleep(0.5)

        # ── Process recipients ───────────────────────────────────────
        recipient_amounts = []
        top_recipients_list = []

        for r in recipients_raw:
            amt = safe_amount(r.get("amount"))
            rid = extract_recipient_id(r)
            rname = r.get("name") or ""
            recipient_amounts.append(amt)

            # Track for cross-NAICS overlap using valid IDs
            if rid:
                if rid not in global_recipients:
                    global_recipients[rid] = {"name": rname, "naics": {}}
                global_recipients[rid]["naics"][naics_code] = amt

        total_spending = sum(recipient_amounts)

        for r in recipients_raw:
            amt = safe_amount(r.get("amount"))
            rid = extract_recipient_id(r)
            share = (amt / total_spending * 100.0) if total_spending > 0 else 0.0
            top_recipients_list.append({
                "name": r.get("name") or "",
                "amount": amt,
                "share_pct": round(share, 4),
                "recipient_id": rid,
            })

            # Track overall top recipient (even without a hash ID)
            if amt > overall_top_amount:
                overall_top_amount = amt
                overall_top_name = r.get("name") or ""
                overall_top_id = rid

        # ── Process geographic data ──────────────────────────────────
        geo_entries = []
        for g in geo_raw:
            gamt = safe_amount(g.get("aggregated_amount"))
            shape_code = g.get("shape_code") or ""
            if gamt > 0 and shape_code and len(shape_code) == 2:
                geo_entries.append({
                    "state_code": shape_code,
                    "state_name": g.get("display_name") or "",
                    "amount": gamt,
                })

        geo_amounts = [e["amount"] for e in geo_entries]
        geo_total = sum(geo_amounts)

        geo_entries.sort(key=lambda e: e["amount"], reverse=True)
        top_states = []
        for e in geo_entries[:5]:
            share = (e["amount"] / geo_total * 100.0) if geo_total > 0 else 0.0
            top_states.append({
                "state_code": e["state_code"],
                "state_name": e["state_name"],
                "amount": e["amount"],
                "share_pct": round(share, 4),
            })

        # ── Process agencies ─────────────────────────────────────────
        top_agency = {"name": "", "amount": 0.0}
        if agencies_raw:
            a = agencies_raw[0]
            top_agency = {
                "name": a.get("name") or "",
                "amount": safe_amount(a.get("amount")),
            }

        # ── Assemble per-NAICS entry ─────────────────────────────────
        report["per_naics"][naics_code] = {
            "total_spending": total_spending,
            "recipient_count": len(recipients_raw),
            "concentration": {
                "hhi": round(compute_hhi(recipient_amounts), 4),
                "cr4": round(compute_cr(recipient_amounts, 4), 4),
                "cr8": round(compute_cr(recipient_amounts, 8), 4),
            },
            "top_recipients": top_recipients_list,
            "geographic": {
                "hhi": round(compute_hhi(geo_amounts), 4),
                "top_states": top_states,
            },
            "top_agency": top_agency,
        }

        print(f"  Done: {len(recipients_raw)} recipients, "
              f"${total_spending:,.2f} total", file=sys.stderr)

    # ── Update overall top using cross-NAICS totals ─────────────────
    for rid, rdata in global_recipients.items():
        recip_total = sum(rdata["naics"].values())
        if recip_total > overall_top_amount:
            overall_top_amount = recip_total
            overall_top_id = rid
            overall_top_name = rdata["name"]

    # ── Cross-NAICS overlap ──────────────────────────────────────────
    overlap = []
    for rid, rdata in global_recipients.items():
        total_amt = sum(rdata["naics"].values())
        if len(rdata["naics"]) >= 2 and total_amt > 0:
            overlap.append({
                "name": rdata["name"],
                "recipient_id": rid,
                "naics_codes": sorted(rdata["naics"].keys()),
                "total_amount": total_amt,
            })
    overlap.sort(key=lambda x: x["total_amount"], reverse=True)
    report["cross_naics_overlap"] = overlap
    print(f"Cross-NAICS overlap: {len(overlap)} recipients", file=sys.stderr)

    # ── Top recipient profile ────────────────────────────────────────
    # Always populate profile with at least basic info from spending data
    profile_data = {
        "name": overall_top_name or "Unknown",
        "recipient_id": overall_top_id or "",
        "location": {},
        "business_categories": [],
        "total_transaction_amount": overall_top_amount,
    }

    # Try to fetch detailed profile from the API if we have a valid hash ID
    if overall_top_id and len(overall_top_id) > 10:
        print(f"Fetching profile for top recipient: "
              f"{overall_top_name}...", file=sys.stderr)
        try:
            api_profile = fetch_recipient_profile(overall_top_id, args.fy)
            if api_profile and isinstance(api_profile, dict) and "name" in api_profile:
                loc = api_profile.get("location") or {}
                profile_data = {
                    "name": api_profile.get("name") or overall_top_name,
                    "recipient_id": overall_top_id,
                    "location": {
                        "state_code": loc.get("state_code") or "",
                        "state_name": loc.get("state_name") or "",
                        "city_name": loc.get("city_name") or "",
                        "country_code": loc.get("country_code") or "",
                        "congressional_district": loc.get("congressional_code") or "",
                    },
                    "business_categories": api_profile.get("business_types") or [],
                    "total_transaction_amount": safe_amount(
                        api_profile.get("total_transaction_amount")
                    ) or overall_top_amount,
                }
        except Exception as exc:
            print(f"  Warning: profile fetch failed: {exc}", file=sys.stderr)

    report["top_recipient_profile"] = profile_data

    # ── Write output ─────────────────────────────────────────────────
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {args.output}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()

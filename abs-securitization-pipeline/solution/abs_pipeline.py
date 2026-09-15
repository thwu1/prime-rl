#!/usr/bin/env python3
"""
ABS-EE Securitization Analytics Pipeline
Fetches loan-level data from SEC EDGAR for SDART 2026-1 and computes
pool statistics, delinquency metrics, and tranche interest.
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

HEADERS = {
    "User-Agent": "ABS-Pipeline admin@example.com",
    "Accept-Encoding": "gzip, deflate",
}


def load_configs():
    with open("/app/trust_config.json") as f:
        trust = json.load(f)
    with open("/app/tranche_structure.json") as f:
        tranches = json.load(f)
    return trust, tranches


# ── EDGAR Filing Discovery ───────────────────────────────────────


def find_ex102_url(trust_cfg):
    """Try multiple methods to find the EX-102 exhibit URL on EDGAR."""
    methods = [
        ("EFTS search", _method_efts),
        ("company search", _method_company_search),
        ("depositor submissions", _method_depositor_subs),
    ]
    for name, method in methods:
        try:
            print(f"Trying {name}...", file=sys.stderr)
            url = method(trust_cfg)
            if url:
                print(f"Found via {name}: {url}", file=sys.stderr)
                return url
        except Exception as e:
            print(f"{name} failed: {e}", file=sys.stderr)
    raise RuntimeError("Could not locate SDART 2026-1 ABS-EE filing on EDGAR")


def _method_efts(trust_cfg):
    """Search EDGAR Full-Text Search System."""
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": f'"{trust_cfg["trust_identifier"]}"',
        "forms": "ABS-EE,ABS-EE/A",
        "dateRange": "custom",
        "startdt": "2026-06-01",
        "enddt": "2026-07-31",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None

    # Find the most recent ABS-EE filing whose display_names mention our trust
    trust_id_lower = trust_cfg["trust_identifier"].lower()
    for hit in hits:
        src = hit.get("_source", {})
        names = " ".join(src.get("display_names", [])).lower()
        if trust_id_lower in names or "sdart" in names and "2026-1" in names:
            adsh = src.get("adsh", "")
            ciks = src.get("ciks", [])
            if adsh and ciks:
                return _get_ex102_from_index(ciks[0], adsh)
    # Fallback: just take the first hit
    src = hits[0].get("_source", {})
    adsh = src.get("adsh", "")
    ciks = src.get("ciks", [])
    if adsh and ciks:
        return _get_ex102_from_index(ciks[0], adsh)
    return None


def _method_company_search(trust_cfg):
    """Search EDGAR by company name (Atom feed) to find trust CIK."""
    url = "https://www.sec.gov/cgi-bin/browse-edgar"
    params = {
        "company": trust_cfg["trust_name"],
        "CIK": "",
        "type": "ABS-EE",
        "dateb": "",
        "owner": "include",
        "count": "20",
        "action": "getcompany",
        "output": "atom",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    atom = "http://www.w3.org/2005/Atom"

    for entry in root.findall(f"{{{atom}}}entry"):
        updated = entry.findtext(f"{{{atom}}}updated", "")
        if "2026-06" in updated or "2026-07" in updated:
            link = entry.find(f"{{{atom}}}link")
            if link is not None:
                href = link.get("href", "")
                m = re.search(r"/Archives/edgar/data/(\d+)/(\d+)", href)
                if m:
                    cik, acc_nd = m.group(1), m.group(2)
                    return _get_ex102_from_index_nd(cik, acc_nd)
            # Try extracting from id
            eid = entry.findtext(f"{{{atom}}}id", "")
            acc_match = re.search(r"accession-number=(\d{10}-\d{2}-\d{6})", eid)
            if acc_match:
                accession = acc_match.group(1)
                # Get CIK from title
                title = entry.findtext(f"{{{atom}}}title", "")
                cik_m = re.search(r"\((\d+)\)", title)
                if cik_m:
                    return _get_ex102_from_index(cik_m.group(1), accession)
    return None


def _method_depositor_subs(trust_cfg):
    """Search depositor's submissions API and check filing indices."""
    cik_padded = trust_cfg["depositor_cik"].zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])

    cik_str = trust_cfg["depositor_cik"].lstrip("0") or "0"

    for i in range(len(forms)):
        if forms[i] not in ("ABS-EE", "ABS-EE/A"):
            continue
        if not (dates[i] >= "2026-06-01" and dates[i] <= "2026-07-31"):
            continue

        acc = accessions[i]
        ex102 = _check_filing_for_trust(cik_str, acc, trust_cfg["asset_type_prefix"])
        if ex102:
            return ex102
        time.sleep(0.15)

    return None


def _check_filing_for_trust(cik, accession, asset_prefix):
    """Check if a filing's documents match the target trust."""
    acc_nd = accession.replace("-", "")
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/index.json"
    resp = requests.get(index_url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        return None

    data = resp.json()
    items = data.get("directory", {}).get("item", [])

    has_sdart = False
    ex102_name = None
    for item in items:
        name = item.get("name", "")
        dtype = item.get("type", "")
        nlower = name.lower()

        if "sdart" in nlower and "2026" in nlower:
            has_sdart = True
        if asset_prefix.lower()[:5] in nlower:
            has_sdart = True

        if "EX-102" in dtype.upper() or "ex102" in nlower or "assetdata" in nlower:
            if name.endswith(".xml"):
                ex102_name = name

    if has_sdart and ex102_name:
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{ex102_name}"
    return None


def _get_ex102_from_index(cik, accession):
    """Get EX-102 URL from filing index using accession with dashes."""
    acc_nd = accession.replace("-", "")
    return _get_ex102_from_index_nd(cik.lstrip("0") or "0", acc_nd)


def _get_ex102_from_index_nd(cik, acc_nd):
    """Get EX-102 URL from filing index using accession without dashes."""
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/index.json"
    resp = requests.get(index_url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        return None
    data = resp.json()
    items = data.get("directory", {}).get("item", [])

    for item in items:
        dtype = item.get("type", "").upper()
        name = item.get("name", "")
        if "EX-102" in dtype:
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{name}"

    for item in items:
        nlower = item.get("name", "").lower()
        if "assetdata" in nlower and nlower.endswith(".xml"):
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{item['name']}"

    return None


# ── Download ──────────────────────────────────────────────────────


def download_file(url, dest):
    """Download a file with streaming."""
    print(f"Downloading {url} ...", file=sys.stderr)
    resp = requests.get(url, headers=HEADERS, timeout=1800, stream=True)
    resp.raise_for_status()
    total = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            total += len(chunk)
    mb = total / 1024 / 1024
    print(f"Downloaded {mb:.1f} MB to {dest}", file=sys.stderr)


# ── XML Parsing & Metrics ────────────────────────────────────────


def parse_and_compute(xml_path):
    """Stream-parse EX-102 XML and compute all pool metrics."""
    ns = "http://www.sec.gov/edgar/document/absee/autoloan/assetdata"
    nsp = f"{{{ns}}}"

    pool_balance = 0.0
    wac_num = 0.0
    wart_num = 0.0
    active_count = 0
    total_count = 0

    delinq = {
        "31-60": {"units": 0, "dollars": 0.0},
        "61-90": {"units": 0, "dollars": 0.0},
        "91-120": {"units": 0, "dollars": 0.0},
    }

    for event, elem in ET.iterparse(xml_path, events=("end",)):
        if elem.tag != f"{nsp}assets":
            continue

        total_count += 1

        end_bal_txt = elem.findtext(f"{nsp}reportingPeriodActualEndBalanceAmount")
        end_bal = float(end_bal_txt) if end_bal_txt else 0.0

        if end_bal > 0:
            active_count += 1
            pool_balance += end_bal

            rate_txt = elem.findtext(f"{nsp}reportingPeriodInterestRatePercentage")
            rate = float(rate_txt) if rate_txt else 0.0
            wac_num += rate * end_bal

            term_txt = elem.findtext(f"{nsp}remainingTermToMaturityNumber")
            term = int(term_txt) if term_txt else 0
            wart_num += term * end_bal

            delinq_txt = elem.findtext(f"{nsp}currentDelinquencyStatus")
            days = int(delinq_txt) if delinq_txt else 0
            if 31 <= days <= 60:
                delinq["31-60"]["units"] += 1
                delinq["31-60"]["dollars"] += end_bal
            elif 61 <= days <= 90:
                delinq["61-90"]["units"] += 1
                delinq["61-90"]["dollars"] += end_bal
            elif 91 <= days <= 120:
                delinq["91-120"]["units"] += 1
                delinq["91-120"]["dollars"] += end_bal

        elem.clear()

        if total_count % 10000 == 0:
            print(f"  Parsed {total_count} loans ({active_count} active)...",
                  file=sys.stderr)

    print(f"Total: {total_count} loans, {active_count} active", file=sys.stderr)

    return {
        "pool_balance": pool_balance,
        "active_count": active_count,
        "wac_num": wac_num,
        "wart_num": wart_num,
        "delinq": delinq,
    }


# ── Tranche Interest ─────────────────────────────────────────────


def compute_tranche_interest(tranche_cfg):
    """Compute accrued interest for each tranche."""
    results = []
    for t in tranche_cfg["tranches"]:
        bal = t["beginning_balance"]
        rate = t["rate_pct"] / 100.0
        dc = t["day_count"]

        if dc == "ACT/360":
            days = t["actual_days"]
            interest = bal * rate * days / 360.0
        elif dc == "30/360":
            interest = bal * rate * 30.0 / 360.0
        else:
            raise ValueError(f"Unknown day count: {dc}")

        results.append({"class": t["class"], "interest": round(interest, 2)})
    return results


# ── Main ──────────────────────────────────────────────────────────


def main():
    trust_cfg, tranche_cfg = load_configs()

    # 1. Find the filing
    ex102_url = find_ex102_url(trust_cfg)

    # 2. Download
    xml_path = "/tmp/sdart_ex102.xml"
    download_file(ex102_url, xml_path)

    # 3. Parse and compute pool metrics
    print("Parsing EX-102 XML...", file=sys.stderr)
    metrics = parse_and_compute(xml_path)

    # 4. Derive summary statistics
    pb = metrics["pool_balance"]
    original = trust_cfg["original_pool_balance"]

    pool_factor = round(pb / original, 6)
    wac_pct = round(100.0 * metrics["wac_num"] / pb, 2) if pb > 0 else 0.0
    wart_months = round(metrics["wart_num"] / pb, 2) if pb > 0 else 0.0

    # 5. Write output
    os.makedirs("/app/output", exist_ok=True)

    pool_summary = {
        "pool_balance": round(pb, 2),
        "pool_factor": pool_factor,
        "wac_pct": wac_pct,
        "wart_months": wart_months,
        "active_loan_count": metrics["active_count"],
    }
    _write_json("/app/output/pool_summary.json", pool_summary)

    delinq_buckets = []
    for label, mn, mx in [("31-60 days", 31, 60),
                           ("61-90 days", 61, 90),
                           ("91-120 days", 91, 120)]:
        key = f"{mn}-{mx}"
        d = metrics["delinq"][key]
        delinq_buckets.append({
            "label": label,
            "min_days": mn,
            "max_days": mx,
            "units": d["units"],
            "dollars": round(d["dollars"], 2),
            "pct": round(100.0 * d["dollars"] / pb, 2) if pb > 0 else 0.0,
        })
    _write_json("/app/output/delinquency.json", {"buckets": delinq_buckets})

    tranche_interest = compute_tranche_interest(tranche_cfg)
    _write_json("/app/output/tranche_interest.json", {"tranches": tranche_interest})

    print("Pipeline complete.", file=sys.stderr)
    print(json.dumps(pool_summary, indent=2))


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()

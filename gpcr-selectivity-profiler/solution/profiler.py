#!/usr/bin/env python3
"""Multi-source pharmacological selectivity profiler with CSV cross-validation.

Queries the GtoPdb REST API and interactions CSV to build selectivity profiles
for ligands across user-specified drug targets.
"""

import argparse
import csv
import io
import json
import math
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from urllib.parse import quote

BASE_URL = "https://www.guidetopharmacology.org/services"
CSV_URL = "https://www.guidetopharmacology.org/DATA/interactions.csv"

_last_request_time = 0.0


def fetch_json(url, retries=4, delay=2):
    """Fetch JSON from a URL with retries and rate limiting."""
    global _last_request_time
    for attempt in range(retries):
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < 0.15:
            time.sleep(0.15 - elapsed)
        _last_request_time = time.time()

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 and attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise
        except Exception:
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise


def strip_html(text):
    """Remove HTML tags from a string."""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)


def parse_affinity(s):
    """Parse an affinity string to float.
    Single values ("8.2") -> float.
    Ranges ("7.1 - 7.5") -> arithmetic mean of endpoints.
    """
    if not s or not s.strip():
        return None
    s = s.strip()
    if " - " in s:
        parts = s.split(" - ")
        try:
            return (float(parts[0].strip()) + float(parts[1].strip())) / 2.0
        except (ValueError, IndexError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


def download_interactions_csv():
    """Download and parse the GtoPdb interactions CSV."""
    req = urllib.request.Request(CSV_URL)
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode('utf-8', errors='replace')

    lines = raw.split('\n')
    # Skip comment/version lines to find the real header
    header_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip().strip('"')
        if stripped.startswith('#') or not stripped:
            continue
        # The header line starts with "Target"
        if 'Target' in stripped and 'Target ID' in line:
            header_idx = i
            break

    csv_content = '\n'.join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(csv_content))
    return list(reader)


def filter_csv_rows(csv_rows, target_ids, species, affinity_type):
    """Filter CSV rows to match query parameters."""
    tid_set = set(target_ids)
    matching = []
    for row in csv_rows:
        try:
            tid = int(row.get('Target ID', '').strip())
        except (ValueError, TypeError):
            continue
        tspecies = row.get('Target Species', '').strip()
        aff_units = row.get('Affinity Units', '').strip()
        if tid in tid_set and tspecies == species and aff_units == affinity_type:
            matching.append(row)
    return matching


def build_csv_medians(csv_rows):
    """Build median affinity per (ligand_id, target_id) from CSV rows."""
    pair_values = defaultdict(list)
    for row in csv_rows:
        try:
            lid = int(row.get('Ligand ID', '').strip())
            tid = int(row.get('Target ID', '').strip())
        except (ValueError, TypeError):
            continue

        # Use Affinity Median column first; fall back to mean of High/Low for ranges
        aff_median = row.get('Affinity Median', '').strip()
        aff_high = row.get('Affinity High', '').strip()
        aff_low = row.get('Affinity Low', '').strip()

        val = None
        if aff_median:
            try:
                val = float(aff_median)
            except ValueError:
                pass
        elif aff_high and aff_low:
            try:
                val = (float(aff_high) + float(aff_low)) / 2.0
            except ValueError:
                pass

        if val is not None:
            pair_values[(lid, tid)].append(val)

    return {k: statistics.median(v) for k, v in pair_values.items()}


def collect_csv_pmids(csv_rows, target_ids):
    """Collect PubMed IDs per ligand from CSV rows."""
    tid_set = set(target_ids)
    pmids_by_ligand = defaultdict(set)
    for row in csv_rows:
        try:
            lid = int(row.get('Ligand ID', '').strip())
            tid = int(row.get('Target ID', '').strip())
        except (ValueError, TypeError):
            continue
        if tid not in tid_set:
            continue
        pmid_str = row.get('PubMed ID', '').strip()
        if pmid_str:
            for part in pmid_str.split('|'):
                part = part.strip()
                if part:
                    try:
                        pmids_by_ligand[lid].add(int(part))
                    except ValueError:
                        pass
    return pmids_by_ligand


def main():
    parser = argparse.ArgumentParser(
        description="GtoPdb multi-source selectivity profiler"
    )
    parser.add_argument("--targets", required=True,
                        help="Comma-separated GtoPdb target IDs")
    parser.add_argument("--species", default="Human",
                        help="Species filter (default: Human)")
    parser.add_argument("--affinity-type", default="pKi",
                        help="Affinity parameter (default: pKi)")
    parser.add_argument("--min-targets", type=int, default=2,
                        help="Min targets per ligand (default: 2)")
    parser.add_argument("--output", required=True,
                        help="Path to write JSON output")
    args = parser.parse_args()

    target_ids = [int(t.strip()) for t in args.targets.split(",")]

    # Short-circuit: if min_targets exceeds queried targets, nothing qualifies
    if args.min_targets > len(target_ids):
        report = {
            "query": {
                "targets": target_ids,
                "species": args.species,
                "affinity_type": args.affinity_type,
                "min_targets": args.min_targets,
            },
            "ligand_count": 0,
            "csv_verification": {
                "rows_matched": 0,
                "pairs_verified": 0,
                "pairs_failed": 0,
                "concordance_rate": 1.0,
            },
            "ligands": [],
        }
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        return

    # ── Phase 1: Fetch interactions from API ──
    pair_affinities = defaultdict(list)
    ligand_meta = {}
    ligand_interaction_types = defaultdict(set)
    ligand_api_pmids = defaultdict(set)

    for tid in target_ids:
        url = (
            f"{BASE_URL}/targets/{tid}/interactions"
            f"?species={quote(args.species)}"
            f"&affinityParameter={quote(args.affinity_type)}"
        )
        try:
            interactions = fetch_json(url)
        except Exception as e:
            print(f"Warning: target {tid}: {e}", file=sys.stderr)
            continue

        if not interactions or not isinstance(interactions, list):
            continue

        for ix in interactions:
            aff = parse_affinity(ix.get("affinity", ""))
            if aff is None:
                continue

            lid = ix["ligandId"]
            pair_affinities[(lid, tid)].append(aff)

            ix_type = ix.get("type", "")
            if ix_type:
                ligand_interaction_types[lid].add(ix_type)

            # Collect PMIDs from refs if present (detailed response)
            refs = ix.get("refs", [])
            if refs:
                for ref in refs:
                    pmid = ref.get("pmid")
                    if pmid:
                        try:
                            ligand_api_pmids[lid].add(int(pmid))
                        except (ValueError, TypeError):
                            pass

            if lid not in ligand_meta:
                ligand_meta[lid] = {
                    "name": strip_html(ix.get("ligandName", "")),
                    "target_names": {},
                }
            ligand_meta[lid]["target_names"][tid] = strip_html(
                ix.get("targetName", "")
            )

    # Aggregate median per (ligand, target)
    ligand_affinities = defaultdict(dict)
    ligand_meas_counts = defaultdict(dict)
    for (lid, tid), affs in pair_affinities.items():
        ligand_affinities[lid][tid] = statistics.median(affs)
        ligand_meas_counts[lid][tid] = len(affs)

    # Filter by min-targets
    qualifying = {
        lid: affs
        for lid, affs in ligand_affinities.items()
        if len(affs) >= args.min_targets
    }

    # ── Phase 2: Download and parse CSV ──
    csv_rows = []
    all_csv_rows = []
    try:
        all_csv_rows = download_interactions_csv()
        csv_rows = filter_csv_rows(
            all_csv_rows, target_ids, args.species, args.affinity_type
        )
    except Exception as e:
        print(f"Warning: CSV download failed: {e}", file=sys.stderr)

    csv_medians = build_csv_medians(csv_rows)
    csv_pmids_by_ligand = collect_csv_pmids(csv_rows, target_ids)

    # ── Phase 3: Cross-validate API vs CSV ──
    pairs_verified = 0
    pairs_failed = 0
    pair_concordance = {}

    for lid in qualifying:
        for tid in qualifying[lid]:
            api_val = ligand_affinities[lid][tid]
            csv_val = csv_medians.get((lid, tid))
            if csv_val is not None:
                if abs(api_val - csv_val) <= 0.15:
                    pairs_verified += 1
                    pair_concordance[(lid, tid)] = True
                else:
                    pairs_failed += 1
                    pair_concordance[(lid, tid)] = False

    total_compared = pairs_verified + pairs_failed
    concordance_rate = pairs_verified / total_compared if total_compared > 0 else 1.0

    csv_verification = {
        "rows_matched": len(csv_rows),
        "pairs_verified": pairs_verified,
        "pairs_failed": pairs_failed,
        "concordance_rate": round(concordance_rate, 4),
    }

    # ── Phase 4: Fetch ligand details and compute metrics ──
    results = []
    for lid in qualifying:
        affs = qualifying[lid]
        meta = ligand_meta[lid]

        # Fetch approved status
        approved = False
        try:
            lig_detail = fetch_json(f"{BASE_URL}/ligands/{lid}")
            if lig_detail and isinstance(lig_detail, dict):
                approved = bool(lig_detail.get("approved", False))
        except Exception:
            pass

        # Fetch molecular properties
        mol_props = {
            "molecular_weight": None, "logp": None,
            "lipinski_violations": None,
            "hbond_acceptors": None, "hbond_donors": None,
        }
        try:
            mp_data = fetch_json(
                f"{BASE_URL}/ligands/{lid}/molecularProperties"
            )
            if mp_data is not None:
                if isinstance(mp_data, list):
                    mp = mp_data[0] if len(mp_data) > 0 else None
                elif isinstance(mp_data, dict):
                    mp = mp_data
                else:
                    mp = None
                if mp:
                    mw = mp.get("molecularWeight")
                    mol_props["molecular_weight"] = (
                        float(mw) if mw is not None else None
                    )
                    lp = mp.get("logP")
                    mol_props["logp"] = float(lp) if lp is not None else None
                    lv = mp.get("lipinskisRuleOfFive")
                    mol_props["lipinski_violations"] = (
                        int(lv) if lv is not None else None
                    )
                    ha = mp.get("hydrogenBondAcceptors")
                    mol_props["hbond_acceptors"] = (
                        int(ha) if ha is not None else None
                    )
                    hd = mp.get("hydrogenBondDonors")
                    mol_props["hbond_donors"] = (
                        int(hd) if hd is not None else None
                    )
        except Exception:
            pass

        # Compute per-ligand selectivity metrics
        aff_values = list(affs.values())
        sorted_affs = sorted(aff_values, reverse=True)

        primary_tid = max(affs, key=affs.get)
        primary_affinity = sorted_affs[0]
        mean_affinity = sum(aff_values) / len(aff_values)
        selectivity_window = max(aff_values) - min(aff_values)

        if len(sorted_affs) >= 2:
            ki_ratio = 10 ** sorted_affs[0] / 10 ** sorted_affs[1]
        else:
            ki_ratio = None

        linear = [10 ** v for v in aff_values]
        total = sum(linear)
        probs = [k / total for k in linear]
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)

        affinities_dict = {
            str(tid): round(v, 4) for tid, v in affs.items()
        }

        # Original affinity in nM: 10^(9 - pAff)
        original_nm = {
            str(tid): round(10 ** (9 - v), 4) for tid, v in affs.items()
        }

        # Measurement counts
        meas_counts = {
            str(tid): ligand_meas_counts[lid].get(tid, 0)
            for tid in affs
        }

        # PMIDs: merge API and CSV sources
        all_pmids = ligand_api_pmids.get(lid, set()) | csv_pmids_by_ligand.get(lid, set())
        pmids = sorted(list(all_pmids))

        # Interaction types
        itypes = sorted(list(ligand_interaction_types.get(lid, set())))

        # Target coverage
        target_coverage = len(affs) / len(target_ids)

        # Per-ligand CSV concordance
        lig_verified = 0
        lig_total = 0
        for tid in affs:
            key = (lid, tid)
            if key in pair_concordance:
                lig_total += 1
                if pair_concordance[key]:
                    lig_verified += 1
        lig_csv_concordance = lig_verified / lig_total if lig_total > 0 else 1.0

        results.append({
            "ligand_id": lid,
            "ligand_name": meta["name"],
            "approved": approved,
            "primary_target_id": primary_tid,
            "primary_target_name": meta["target_names"].get(primary_tid, ""),
            "primary_affinity": round(primary_affinity, 4),
            "mean_affinity": round(mean_affinity, 4),
            "selectivity_window": round(selectivity_window, 4),
            "ki_selectivity_ratio": (
                round(ki_ratio, 4) if ki_ratio is not None else None
            ),
            "selectivity_entropy": round(entropy, 4),
            "affinities": affinities_dict,
            "original_affinity_nm": original_nm,
            "measurement_count": meas_counts,
            "pmids": pmids,
            "interaction_types": itypes,
            "target_coverage": round(target_coverage, 4),
            "csv_concordance": round(lig_csv_concordance, 4),
            "molecular_properties": mol_props,
        })

    # Sort: selectivity_window desc, then primary_affinity desc
    results.sort(
        key=lambda x: (-x["selectivity_window"], -x["primary_affinity"])
    )

    report = {
        "query": {
            "targets": target_ids,
            "species": args.species,
            "affinity_type": args.affinity_type,
            "min_targets": args.min_targets,
        },
        "ligand_count": len(results),
        "csv_verification": csv_verification,
        "ligands": results,
    }

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()

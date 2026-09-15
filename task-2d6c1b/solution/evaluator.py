#!/usr/bin/env python3
"""Solution: metagenome profiling submission audit.

Parses NCBI taxonomy (including merged.dmp), CAMI profiles,
diagnoses data quality issues, computes corrected metrics,
and produces all required outputs.

"""

import csv
import json
import os
from collections import defaultdict

STANDARD_RANKS = [
    "superkingdom", "phylum", "class", "order", "family", "genus", "species"
]


# ---- Taxonomy parsing ----

def parse_taxonomy(nodes_path, names_path, merged_path):
    parent = {}
    rank = {}
    children = defaultdict(set)
    with open(nodes_path) as f:
        for line in f:
            parts = line.strip().rstrip("|").split("\t|\t")
            tid = int(parts[0].strip())
            pid = int(parts[1].strip())
            r = parts[2].strip()
            parent[tid] = pid
            rank[tid] = r
            if tid != pid:
                children[pid].add(tid)

    name = {}
    with open(names_path) as f:
        for line in f:
            parts = line.strip().rstrip("|").split("\t|\t")
            tid = int(parts[0].strip())
            n = parts[1].strip()
            nc = parts[3].strip() if len(parts) > 3 else ""
            if nc == "scientific name":
                name[tid] = n

    merged = {}
    with open(merged_path) as f:
        for line in f:
            parts = line.strip().rstrip("|").split("\t|\t")
            if len(parts) >= 2:
                old_id = int(parts[0].strip())
                new_id = int(parts[1].strip())
                merged[old_id] = new_id

    return parent, rank, name, children, merged


# ---- CAMI profile parsing ----

def parse_cami_profile(filepath):
    """Parse a CAMI profiling format file. Returns dict sample_id -> entries list."""
    samples = {}
    current_sample = None
    in_data = False
    with open(filepath) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            if line.startswith("@SampleID:"):
                current_sample = line.split(":", 1)[1].strip()
                samples[current_sample] = []
                in_data = False
                continue
            if line.startswith("@@"):
                in_data = True
                continue
            if line.startswith("@"):
                continue
            if in_data and current_sample is not None:
                parts = line.split("\t")
                if len(parts) >= 5:
                    samples[current_sample].append({
                        "taxid": int(parts[0].strip()),
                        "rank": parts[1].strip(),
                        "taxpath": parts[2].strip(),
                        "taxpathsn": parts[3].strip(),
                        "percentage": float(parts[4].strip()),
                    })
    return samples


def parse_echo_fixed(filepath):
    """Parse echo's profile, fixing the missing @SampleID for second sample.

    We detect a @@TAXID header without a preceding @SampleID and assign 'S2'.
    """
    samples = {}
    current_sample = None
    in_data = False
    sample_count = 0

    with open(filepath) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            if line.startswith("@SampleID:"):
                current_sample = line.split(":", 1)[1].strip()
                samples[current_sample] = []
                in_data = False
                sample_count += 1
                continue
            if line.startswith("@@"):
                if not in_data and current_sample is not None:
                    in_data = True
                elif in_data:
                    # Second @@ without @SampleID: this is the missing header
                    sample_count += 1
                    current_sample = "S2"
                    samples[current_sample] = []
                    in_data = True
                else:
                    in_data = True
                continue
            if line.startswith("@"):
                continue
            if in_data and current_sample is not None:
                parts = line.split("\t")
                if len(parts) >= 5:
                    samples[current_sample].append({
                        "taxid": int(parts[0].strip()),
                        "rank": parts[1].strip(),
                        "taxpath": parts[2].strip(),
                        "taxpathsn": parts[3].strip(),
                        "percentage": float(parts[4].strip()),
                    })
    return samples


# ---- Issue diagnosis ----

def diagnose_issues(tools_data, parent_map, rank_map, merged_map):
    """Diagnose data quality issues in all tool submissions."""
    issues = []
    valid_taxids = set(parent_map.keys())

    for tool_name, samples in tools_data.items():
        for sample_id, entries in samples.items():
            # Check for merged/deprecated taxids
            for e in entries:
                if e["taxid"] not in valid_taxids and e["taxid"] in merged_map:
                    new_id = merged_map[e["taxid"]]
                    issues.append({
                        "tool": tool_name,
                        "sample": sample_id,
                        "issue_type": "merged_taxid",
                        "description": (
                            f"TAXID {e['taxid']} is deprecated/merged; "
                            f"maps to {new_id} in merged.dmp"
                        ),
                    })
                elif e["taxid"] not in valid_taxids:
                    issues.append({
                        "tool": tool_name,
                        "sample": sample_id,
                        "issue_type": "invalid_taxid",
                        "description": f"TAXID {e['taxid']} not found in taxonomy",
                    })

            # Check abundance overflow at each rank
            for rk in STANDARD_RANKS:
                rank_entries = [e for e in entries if e["rank"] == rk]
                total = sum(e["percentage"] for e in rank_entries)
                if total > 100.5:  # tolerance
                    issues.append({
                        "tool": tool_name,
                        "sample": sample_id,
                        "issue_type": "abundance_overflow",
                        "description": (
                            f"Abundances at {rk} sum to {total:.1f}%, exceeding 100%"
                        ),
                    })
                    break  # Report once per sample

            # Check duplicate taxids at same rank
            for rk in STANDARD_RANKS:
                rank_entries = [e for e in entries if e["rank"] == rk]
                taxids = [e["taxid"] for e in rank_entries]
                seen = set()
                for tid in taxids:
                    if tid in seen:
                        issues.append({
                            "tool": tool_name,
                            "sample": sample_id,
                            "issue_type": "duplicate_taxid",
                            "description": (
                                f"TAXID {tid} appears multiple times at rank {rk}"
                            ),
                        })
                        break
                    seen.add(tid)

    # Check for echo's missing sample
    # Compare sample counts across tools
    sample_ids = set()
    for tool_name, samples in tools_data.items():
        sample_ids.update(samples.keys())

    for tool_name, samples in tools_data.items():
        missing = sample_ids - set(samples.keys())
        if missing:
            for s in missing:
                issues.append({
                    "tool": tool_name,
                    "sample": s,
                    "issue_type": "malformed_header",
                    "description": (
                        f"Sample {s} missing from profile — likely @SampleID "
                        f"header is absent or malformed"
                    ),
                })

    return issues


# ---- Correction ----

def correct_entries(entries, merged_map):
    """Apply corrections to a list of profile entries:
    - Resolve merged taxids
    - Normalize if sum > 100
    - Deduplicate taxids at same rank by summing
    """
    corrected = []
    for e in entries:
        new_e = dict(e)
        if new_e["taxid"] in merged_map:
            new_e["taxid"] = merged_map[new_e["taxid"]]
        corrected.append(new_e)

    # Deduplicate: sum percentages for same (taxid, rank)
    deduped = {}
    for e in corrected:
        key = (e["taxid"], e["rank"])
        if key in deduped:
            deduped[key]["percentage"] += e["percentage"]
        else:
            deduped[key] = dict(e)
    corrected = list(deduped.values())

    # Normalize if any rank sums > 100
    for rk in STANDARD_RANKS:
        rank_entries = [e for e in corrected if e["rank"] == rk]
        total = sum(e["percentage"] for e in rank_entries)
        if total > 100.5:
            factor = 100.0 / total
            for e in rank_entries:
                e["percentage"] *= factor

    return corrected


# ---- Metric computation ----

def compute_metrics(pred_entries, gs_entries, rank):
    pred_at_rank = {e["taxid"]: e["percentage"]
                    for e in pred_entries if e["rank"] == rank}
    gs_at_rank = {e["taxid"]: e["percentage"]
                  for e in gs_entries if e["rank"] == rank}

    all_taxa = set(pred_at_rank.keys()) | set(gs_at_rank.keys())
    l1 = sum(abs(pred_at_rank.get(t, 0.0) - gs_at_rank.get(t, 0.0))
             for t in all_taxa)

    pred_taxa = set(pred_at_rank.keys())
    gs_taxa = set(gs_at_rank.keys())
    tp = len(pred_taxa & gs_taxa)
    precision = tp / len(pred_taxa) if pred_taxa else 0.0
    recall = tp / len(gs_taxa) if gs_taxa else 0.0

    return l1, precision, recall


# ---- Main ----

def main():
    # Parse taxonomy
    parent_map, rank_map, name_map, children_map, merged_map = parse_taxonomy(
        "/opt/taskdata/taxonomy/nodes.dmp",
        "/opt/taskdata/taxonomy/names.dmp",
        "/opt/taskdata/taxonomy/merged.dmp",
    )

    # Parse gold standard
    gs = parse_cami_profile("/opt/taskdata/gold_standard.profile")

    # Parse submissions (standard parsing)
    sub_dir = "/opt/taskdata/submissions"
    tools_raw = {}
    for fname in sorted(os.listdir(sub_dir)):
        if fname.endswith(".profile"):
            tool_name = fname.replace(".profile", "")
            tools_raw[tool_name] = parse_cami_profile(
                os.path.join(sub_dir, fname)
            )

    # Diagnose issues
    issues = diagnose_issues(tools_raw, parent_map, rank_map, merged_map)

    # Fix echo: re-parse with header recovery
    echo_fixed = parse_echo_fixed(
        os.path.join(sub_dir, "profiler_echo.profile")
    )

    # Build corrected tools data
    tools_corrected = {}
    for tool_name, samples in tools_raw.items():
        if tool_name == "profiler_echo":
            # Use fixed parse
            corrected_samples = {}
            for sid, entries in echo_fixed.items():
                corrected_samples[sid] = correct_entries(entries, merged_map)
            tools_corrected[tool_name] = corrected_samples
        else:
            corrected_samples = {}
            for sid, entries in samples.items():
                corrected_samples[sid] = correct_entries(entries, merged_map)
            tools_corrected[tool_name] = corrected_samples

    # Compute corrected metrics
    eval_rows = []
    for tool_name in sorted(tools_corrected.keys()):
        tool_samples = tools_corrected[tool_name]
        for sample_id in sorted(gs.keys()):
            if sample_id not in tool_samples:
                continue
            pred = tool_samples[sample_id]
            gold = gs[sample_id]
            for rk in STANDARD_RANKS:
                l1, prec, rec = compute_metrics(pred, gold, rk)
                eval_rows.append({
                    "tool": tool_name,
                    "sample": sample_id,
                    "rank": rk,
                    "l1_norm": f"{l1:.6f}",
                    "precision": f"{prec:.6f}",
                    "recall": f"{rec:.6f}",
                })

    # Write corrected_metrics.tsv
    os.makedirs("/app/audit", exist_ok=True)
    with open("/app/audit/corrected_metrics.tsv", "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["tool", "sample", "rank", "l1_norm", "precision", "recall"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(eval_rows)

    # Compute ranking by mean L1
    tool_l1 = defaultdict(list)
    for row in eval_rows:
        tool_l1[row["tool"]].append(float(row["l1_norm"]))
    tool_mean = {t: sum(vs) / len(vs) for t, vs in tool_l1.items()}
    ranked = sorted(tool_mean.keys(), key=lambda t: tool_mean[t])

    with open("/app/audit/ranking.txt", "w") as f:
        for t in ranked:
            f.write(t + "\n")

    # Write issues.json
    with open("/app/audit/issues.json", "w") as f:
        json.dump(issues, f, indent=2)

    print(f"Audit complete: {len(eval_rows)} metric rows, {len(issues)} issues.")
    print(f"Ranking: {ranked}")
    print(f"Mean L1: {tool_mean}")


if __name__ == "__main__":
    main()

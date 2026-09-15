#!/usr/bin/env python3
"""
CASP16 Multi-Metric Group Ranking Pipeline
"""

import csv
import json
import math
import os
import re
import sqlite3
from collections import defaultdict


def mean(vals):
    return sum(vals) / len(vals) if vals else 0.0


def stdev(vals):
    """Sample standard deviation."""
    if len(vals) < 2:
        return 0.0
    m = mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def compute_casp_zscores(group_scores):
    """
    CASP iterative z-score normalization:
    1. Compute raw z-scores from scores
    2. Remove outliers (raw z < -2.0)
    3. Recompute z-scores from remaining models' stats
    4. Clamp final z-scores at -2.0
    Returns dict of group -> z-score and whether any outliers were removed.
    """
    if len(group_scores) < 2:
        return {g: 0.0 for g in group_scores}, False

    vals = list(group_scores.values())
    m1 = mean(vals)
    s1 = stdev(vals)
    if s1 < 1e-10:
        return {g: 0.0 for g in group_scores}, False

    # Step 1: Raw z-scores
    raw_z = {g: (group_scores[g] - m1) / s1 for g in group_scores}

    # Step 2: Remove outliers
    kept = {g: group_scores[g] for g in group_scores if raw_z[g] >= -2.0}
    had_outliers = len(kept) < len(group_scores)

    if len(kept) < 2:
        return {g: max(raw_z[g], -2.0) for g in group_scores}, had_outliers

    # Step 3: Recompute with reduced set statistics
    kept_vals = list(kept.values())
    m2 = mean(kept_vals)
    s2 = stdev(kept_vals)

    if s2 < 1e-10:
        return {g: 0.0 for g in group_scores}, had_outliers

    # Step 4: Final z-scores for ALL groups, clamped at -2.0
    return {g: max((group_scores[g] - m2) / s2, -2.0) for g in group_scores}, had_outliers


def kendall_tau_b(ranks1, ranks2, items):
    """Compute Kendall tau-b rank correlation."""
    n = len(items)
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = items[i]
            b = items[j]
            d1 = ranks1[a] - ranks1[b]
            d2 = ranks2[a] - ranks2[b]
            if d1 * d2 > 0:
                concordant += 1
            elif d1 * d2 < 0:
                discordant += 1

    n_pairs = n * (n - 1) // 2

    from collections import Counter

    def count_ties(ranks, items):
        rank_vals = [ranks[g] for g in items]
        counts = Counter(rank_vals)
        return sum(c * (c - 1) // 2 for c in counts.values())

    t1 = count_ties(ranks1, items)
    t2 = count_ties(ranks2, items)

    denom = math.sqrt((n_pairs - t1) * (n_pairs - t2))
    if denom == 0:
        return 0.0
    return (concordant - discordant) / denom


def main():
    data_path = "/app/data/casp16_prot_domains_scores.csv"
    results_dir = "/app/results"
    os.makedirs(results_dir, exist_ok=True)

    metrics = ["GDT_TS", "LDDT", "TMscore", "CAD_AA", "GDT_HA"]

    # Parse CSV
    with open(data_path) as f:
        lines = f.readlines()

    header = lines[0].split()
    col_idx = {name: i for i, name in enumerate(header)}
    metric_cols = {m: col_idx[m] for m in metrics}

    # Parse data: domain -> metric -> [(group, value)]
    domain_metric_data = defaultdict(lambda: defaultdict(list))
    all_groups = set()
    all_first_count = 0
    first_model_records = []

    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 25:
            continue
        # Skip repeated header lines
        if fields[0] == "#":
            continue
        model_name = fields[1]
        m = re.match(r"^(.+)TS(\d+)_(\d+)-(.+)$", model_name)
        if not m:
            continue
        target = m.group(1)
        group = m.group(2)
        model_num = m.group(3)
        domain = m.group(4)
        td = f"{target}-{domain}"

        if model_num != "1":
            continue

        all_first_count += 1
        all_groups.add(group)

        record_vals = {}
        for metric in metrics:
            val_str = fields[metric_cols[metric]]
            try:
                v = float(val_str)
                record_vals[metric] = v
                domain_metric_data[td][metric].append((group, v))
            except ValueError:
                record_vals[metric] = None

        first_model_records.append((
            target, group, domain,
            record_vals.get("GDT_TS"),
            record_vals.get("LDDT"),
            record_vals.get("TMscore"),
            record_vals.get("CAD_AA"),
            record_vals.get("GDT_HA"),
        ))

    total_domains = len(domain_metric_data)
    total_groups = len(all_groups)

    # Compute z-scores per domain per metric
    group_metric_zscores = defaultdict(lambda: defaultdict(list))
    domains_with_outliers = 0

    for td in sorted(domain_metric_data.keys()):
        for metric in metrics:
            data = domain_metric_data[td][metric]
            if len(data) < 3:
                continue
            scores = {g: v for g, v in data}
            zscores, had_outliers = compute_casp_zscores(scores)
            for g, z in zscores.items():
                group_metric_zscores[g][metric].append(z)

        # Track outlier domains for GDT_TS
        gdt_data = domain_metric_data[td]["GDT_TS"]
        if len(gdt_data) >= 3:
            scores = {g: v for g, v in gdt_data}
            vals = list(scores.values())
            m1 = mean(vals)
            s1 = stdev(vals)
            if s1 > 1e-10:
                raw_z = {g: (scores[g] - m1) / s1 for g in scores}
                if any(z < -2.0 for z in raw_z.values()):
                    domains_with_outliers += 1

    # Aggregate z-scores per group per metric
    group_agg = {}
    for g in group_metric_zscores:
        agg = {"n_domains": 0}
        for metric in metrics:
            zlist = group_metric_zscores[g][metric]
            if zlist:
                agg[f"sum_z_{metric}"] = sum(zlist)
                agg[f"avg_z_{metric}"] = mean(zlist)
                agg["n_domains"] = max(agg["n_domains"], len(zlist))
            else:
                agg[f"sum_z_{metric}"] = 0.0
                agg[f"avg_z_{metric}"] = 0.0
        group_agg[g] = agg

    # Rank by each metric's SUM z-score
    metric_short = {
        "GDT_TS": "gdt",
        "LDDT": "lddt",
        "TMscore": "tm",
        "CAD_AA": "cad",
        "GDT_HA": "ha",
    }

    for metric in metrics:
        short = metric_short[metric]
        sorted_groups = sorted(
            group_agg.keys(), key=lambda g: -group_agg[g][f"sum_z_{metric}"]
        )
        for rank, g in enumerate(sorted_groups, 1):
            group_agg[g][f"rank_{short}"] = rank

    # Write group_rankings.csv (sorted by rank_gdt)
    ranking_rows = sorted(group_agg.keys(), key=lambda g: group_agg[g]["rank_gdt"])

    with open(os.path.join(results_dir, "group_rankings.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "group", "n_domains",
            "sum_z_gdt", "rank_gdt",
            "sum_z_lddt", "rank_lddt",
            "sum_z_tm", "rank_tm",
            "sum_z_cad", "rank_cad",
            "sum_z_ha", "rank_ha",
        ])
        for g in ranking_rows:
            a = group_agg[g]
            writer.writerow([
                g,
                a["n_domains"],
                f"{a['sum_z_GDT_TS']:.4f}",
                a["rank_gdt"],
                f"{a['sum_z_LDDT']:.4f}",
                a["rank_lddt"],
                f"{a['sum_z_TMscore']:.4f}",
                a["rank_tm"],
                f"{a['sum_z_CAD_AA']:.4f}",
                a["rank_cad"],
                f"{a['sum_z_GDT_HA']:.4f}",
                a["rank_ha"],
            ])

    # Kendall tau-b: pairwise between metric rankings
    common_groups = [
        g for g in group_metric_zscores
        if all(group_metric_zscores[g].get(m) for m in metrics)
    ]

    metric_rank_dicts = {}
    for metric in metrics:
        ranked = sorted(
            common_groups, key=lambda g: -sum(group_metric_zscores[g][metric])
        )
        metric_rank_dicts[metric] = {g: rank + 1 for rank, g in enumerate(ranked)}

    with open(os.path.join(results_dir, "metric_correlations.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric1", "metric2", "kendall_tau"])
        for i in range(len(metrics)):
            for j in range(i + 1, len(metrics)):
                m1_name = metrics[i]
                m2_name = metrics[j]
                tau = kendall_tau_b(
                    metric_rank_dicts[m1_name],
                    metric_rank_dicts[m2_name],
                    common_groups,
                )
                writer.writerow([m1_name, m2_name, f"{tau:.4f}"])

    # Discriminating domains (top 10 by GDT_TS std dev, min 10 submissions)
    domain_stats = []
    for td in sorted(domain_metric_data.keys()):
        gdt_data = domain_metric_data[td]["GDT_TS"]
        if len(gdt_data) < 10:
            continue
        vals = [v for _, v in gdt_data]
        s = stdev(vals)
        m_val = mean(vals)
        med = median(vals)
        domain_stats.append((td, s, m_val, med, len(gdt_data)))

    domain_stats.sort(key=lambda x: -x[1])
    top10 = domain_stats[:10]

    with open(os.path.join(results_dir, "discriminating_domains.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["domain", "std_gdt", "mean_gdt", "median_gdt", "n_groups"])
        for td, s, m_val, med, n in top10:
            writer.writerow([td, f"{s:.2f}", f"{m_val:.2f}", f"{med:.2f}", n])

    # Summary JSON
    gdt_ranking = sorted(
        group_agg.keys(), key=lambda g: group_agg[g]["rank_gdt"]
    )
    lddt_ranking = sorted(
        group_agg.keys(), key=lambda g: group_agg[g]["rank_lddt"]
    )

    summary = {
        "total_first_models": all_first_count,
        "total_domains": total_domains,
        "total_groups": total_groups,
        "domains_with_outliers_removed": domains_with_outliers,
        "top3_gdt": gdt_ranking[:3],
        "top3_lddt": lddt_ranking[:3],
    }

    with open(os.path.join(results_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    # Create SQLite database
    db_path = os.path.join(results_dir, "casp16_analysis.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE first_models (
        target TEXT,
        group_id TEXT,
        domain TEXT,
        GDT_TS REAL,
        LDDT REAL,
        TMscore REAL,
        CAD_AA REAL,
        GDT_HA REAL
    )""")
    cur.executemany(
        "INSERT INTO first_models VALUES (?,?,?,?,?,?,?,?)",
        first_model_records,
    )

    cur.execute("""CREATE TABLE group_rankings (
        group_id TEXT,
        n_domains INTEGER,
        metric TEXT,
        sum_zscore REAL,
        avg_zscore REAL,
        rank INTEGER
    )""")
    for g in group_agg:
        for metric in metrics:
            short = metric_short[metric]
            cur.execute(
                "INSERT INTO group_rankings VALUES (?,?,?,?,?,?)",
                (
                    g,
                    group_agg[g]["n_domains"],
                    metric,
                    group_agg[g][f"sum_z_{metric}"],
                    group_agg[g][f"avg_z_{metric}"],
                    group_agg[g][f"rank_{short}"],
                ),
            )

    conn.commit()
    conn.close()

    print(f"Pipeline complete. Results written to {results_dir}/")
    print(f"  First models: {all_first_count}")
    print(f"  Domains: {total_domains}")
    print(f"  Groups: {total_groups}")
    print(f"  Domains with outlier removal: {domains_with_outliers}")
    print(f"  Top 3 by GDT_TS: {gdt_ranking[:3]}")
    print(f"  Top 3 by LDDT: {lddt_ranking[:3]}")
    print(f"  SQLite database: {db_path}")


if __name__ == "__main__":
    main()

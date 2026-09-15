#!/usr/bin/env python3
"""Reference solution: audit data quality, clean citation graph, compute bibliometrics."""

import duckdb
import pandas as pd
import os

DB_PATH = "/app/patents.duckdb"
OUTPUT_DIR = "/app/output"


def compute_data_issues(con):
    issues = []

    count = con.execute(
        "SELECT COUNT(*) FROM citations WHERE citing_pub = cited_pub"
    ).fetchone()[0]
    if count > 0:
        issues.append(("self_referencing_citation", count))

    count = con.execute(
        "SELECT (SELECT COUNT(*) FROM citations) - "
        "(SELECT COUNT(*) FROM (SELECT DISTINCT citing_pub, cited_pub FROM citations))"
    ).fetchone()[0]
    if count > 0:
        issues.append(("duplicate_citation_edge", count))

    count = con.execute(
        "SELECT COUNT(*) FROM citations c "
        "WHERE NOT EXISTS (SELECT 1 FROM publications p WHERE p.publication_number = c.cited_pub)"
    ).fetchone()[0]
    if count > 0:
        issues.append(("orphan_citation", count))

    count = con.execute(
        "SELECT COUNT(*) FROM publications WHERE grant_date < filing_date"
    ).fetchone()[0]
    if count > 0:
        issues.append(("inverted_dates", count))

    count = con.execute(
        "SELECT COUNT(*) FROM publications WHERE assignee_harmonized IS NULL"
    ).fetchone()[0]
    if count > 0:
        issues.append(("null_assignee", count))

    df = pd.DataFrame(issues, columns=["issue", "count"])
    df = df.sort_values(["count", "issue"], ascending=[False, True]).reset_index(drop=True)
    return df


def compute_originality(con):
    query = """
    WITH clean_cit AS (
        SELECT DISTINCT citing_pub, cited_pub
        FROM citations
        WHERE citing_pub != cited_pub
          AND cited_pub IN (SELECT publication_number FROM publications)
    ),
    us_b2 AS (
        SELECT publication_number, grant_date, assignee_harmonized
        FROM publications
        WHERE country_code = 'US' AND kind_code = 'B2'
          AND grant_date >= '2015-01-01' AND grant_date <= '2018-12-31'
    ),
    backward AS (
        SELECT c.citing_pub, c.cited_pub
        FROM clean_cit c
        INNER JOIN us_b2 u ON c.citing_pub = u.publication_number
    ),
    bc_counts AS (
        SELECT citing_pub, COUNT(*) AS num_backward
        FROM backward
        GROUP BY citing_pub
        HAVING COUNT(*) >= 5
    ),
    cited_ipc4 AS (
        SELECT b.citing_pub, SUBSTRING(i.code, 1, 4) AS ipc4
        FROM backward b
        INNER JOIN ipc_codes i ON b.cited_pub = i.publication_number
        WHERE b.citing_pub IN (SELECT citing_pub FROM bc_counts)
    ),
    ipc4_dist AS (
        SELECT citing_pub, ipc4, COUNT(*) AS n
        FROM cited_ipc4
        GROUP BY citing_pub, ipc4
    ),
    ipc4_totals AS (
        SELECT citing_pub, SUM(n) AS total_n, COUNT(*) AS num_ipc4_classes
        FROM ipc4_dist
        GROUP BY citing_pub
    ),
    hhi_calc AS (
        SELECT d.citing_pub,
               SUM(POWER(CAST(d.n AS DOUBLE) / t.total_n, 2)) AS hhi,
               t.num_ipc4_classes
        FROM ipc4_dist d
        JOIN ipc4_totals t ON d.citing_pub = t.citing_pub
        GROUP BY d.citing_pub, t.num_ipc4_classes
    ),
    self_cite AS (
        SELECT b.citing_pub,
               SUM(CASE WHEN p_citing.assignee_harmonized IS NOT NULL
                         AND p_citing.assignee_harmonized = p_cited.assignee_harmonized
                    THEN 1 ELSE 0 END) AS self_cite_count,
               COUNT(*) AS total_backward
        FROM backward b
        JOIN publications p_citing ON b.citing_pub = p_citing.publication_number
        JOIN publications p_cited ON b.cited_pub = p_cited.publication_number
        WHERE b.citing_pub IN (SELECT citing_pub FROM bc_counts)
        GROUP BY b.citing_pub
    )
    SELECT h.citing_pub AS publication_number,
           CAST(u.grant_date AS VARCHAR) AS grant_date,
           CAST(bc.num_backward AS INTEGER) AS num_backward,
           CAST(h.num_ipc4_classes AS INTEGER) AS num_ipc4_classes,
           ROUND(1.0 - h.hhi, 6) AS originality,
           ROUND(CAST(sc.self_cite_count AS DOUBLE) / sc.total_backward, 6) AS self_cite_share
    FROM hhi_calc h
    JOIN us_b2 u ON h.citing_pub = u.publication_number
    JOIN bc_counts bc ON h.citing_pub = bc.citing_pub
    JOIN self_cite sc ON h.citing_pub = sc.citing_pub
    ORDER BY originality DESC, publication_number ASC
    LIMIT 20
    """
    return con.execute(query).fetchdf()


def compute_portfolio(con):
    query = """
    WITH clean_cit AS (
        SELECT DISTINCT citing_pub, cited_pub
        FROM citations
        WHERE citing_pub != cited_pub
          AND cited_pub IN (SELECT publication_number FROM publications)
    ),
    valid_pubs AS (
        SELECT * FROM publications WHERE assignee_harmonized IS NOT NULL
    ),
    assignee_counts AS (
        SELECT assignee_harmonized AS assignee, COUNT(*) AS num_patents
        FROM valid_pubs
        GROUP BY assignee_harmonized
        ORDER BY num_patents DESC, assignee ASC
        LIMIT 10
    ),
    assignee_cpc AS (
        SELECT p.assignee_harmonized AS assignee, c.section, COUNT(*) AS cnt
        FROM valid_pubs p
        INNER JOIN cpc_codes c ON p.publication_number = c.publication_number
        WHERE p.assignee_harmonized IN (SELECT assignee FROM assignee_counts)
        GROUP BY p.assignee_harmonized, c.section
    ),
    cpc_totals AS (
        SELECT assignee, SUM(cnt) AS total
        FROM assignee_cpc
        GROUP BY assignee
    ),
    hhi_calc AS (
        SELECT ac.assignee,
               SUM(POWER(CAST(ac.cnt AS DOUBLE) / ct.total, 2)) AS hhi
        FROM assignee_cpc ac
        JOIN cpc_totals ct ON ac.assignee = ct.assignee
        GROUP BY ac.assignee
    ),
    fwd_per_patent AS (
        SELECT p.assignee_harmonized AS assignee, p.publication_number,
               COUNT(c.citing_pub) AS fwd
        FROM valid_pubs p
        LEFT JOIN clean_cit c ON p.publication_number = c.cited_pub
        WHERE p.assignee_harmonized IN (SELECT assignee FROM assignee_counts)
        GROUP BY p.assignee_harmonized, p.publication_number
    ),
    avg_fwd AS (
        SELECT assignee, AVG(CAST(fwd AS DOUBLE)) AS avg_clean_fwd_raw
        FROM fwd_per_patent
        GROUP BY assignee
    )
    SELECT ac.assignee,
           CAST(ac.num_patents AS INTEGER) AS num_patents,
           1.0 - h.hhi AS tech_diversity_raw,
           af.avg_clean_fwd_raw
    FROM assignee_counts ac
    JOIN hhi_calc h ON ac.assignee = h.assignee
    JOIN avg_fwd af ON ac.assignee = af.assignee
    """
    df = con.execute(query).fetchdf()

    def minmax(s):
        mn, mx = s.min(), s.max()
        if mx == mn:
            return pd.Series([0.0] * len(s), index=s.index, dtype=float)
        return (s - mn) / (mx - mn)

    df["composite_score"] = (
        0.4 * minmax(df["num_patents"].astype(float)) +
        0.3 * minmax(df["tech_diversity_raw"]) +
        0.3 * minmax(df["avg_clean_fwd_raw"])
    ).round(6)

    df["tech_diversity"] = df["tech_diversity_raw"].round(6)
    df["avg_clean_fwd"] = df["avg_clean_fwd_raw"].round(4)

    result = df[["assignee", "num_patents", "tech_diversity",
                  "avg_clean_fwd", "composite_score"]].copy()
    result = result.sort_values(
        ["composite_score", "assignee"], ascending=[False, True]
    ).reset_index(drop=True)
    return result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    con = duckdb.connect(DB_PATH, read_only=True)

    issues = compute_data_issues(con)
    issues.to_csv(os.path.join(OUTPUT_DIR, "data_issues.csv"), index=False)
    print(f"Wrote data_issues.csv ({len(issues)} rows)")

    originality = compute_originality(con)
    originality.to_csv(os.path.join(OUTPUT_DIR, "originality_analysis.csv"), index=False)
    print(f"Wrote originality_analysis.csv ({len(originality)} rows)")

    portfolio = compute_portfolio(con)
    portfolio.to_csv(os.path.join(OUTPUT_DIR, "portfolio_ranking.csv"), index=False)
    print(f"Wrote portfolio_ranking.csv ({len(portfolio)} rows)")

    con.close()
    print("All outputs generated.")


if __name__ == "__main__":
    main()

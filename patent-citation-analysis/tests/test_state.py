
import pytest
import duckdb
import pandas as pd
import os
import math

DB_PATH = "/app/patents.duckdb"
OUTPUT_DIR = "/app/output"

# ---------------------------------------------------------------------------
# Gold SQL queries
# ---------------------------------------------------------------------------

QUERY_ORIGINALITY = """
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

QUERY_PORTFOLIO_RAW = """
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

# ---------------------------------------------------------------------------
# Comparison utilities
# ---------------------------------------------------------------------------

def normalize_value(val):
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s.lower() in ("true", "1", "yes"):
        return True
    if s.lower() in ("false", "0", "no"):
        return False
    try:
        return float(s)
    except (ValueError, TypeError):
        return s


def values_match(pred_val, gold_val, tolerance=1e-3):
    p = normalize_value(pred_val)
    g = normalize_value(gold_val)

    if p is None and g is None:
        return True
    if p is None or g is None:
        return False

    if isinstance(g, bool) or isinstance(p, bool):
        return bool(p) == bool(g)

    if isinstance(g, float) and isinstance(p, float):
        if g == 0.0 and p == 0.0:
            return True
        return math.isclose(p, g, abs_tol=tolerance, rel_tol=1e-3)

    return str(p) == str(g)


def compare_dataframes(pred_df, gold_df, tolerance=1e-3):
    gold_cols = list(gold_df.columns)
    for col in gold_cols:
        assert col in pred_df.columns, f"Missing column: {col}"

    pred_df = pred_df[gold_cols].reset_index(drop=True)
    gold_df = gold_df.reset_index(drop=True)

    assert len(pred_df) == len(gold_df), (
        f"Row count mismatch: got {len(pred_df)}, expected {len(gold_df)}"
    )

    for i in range(len(gold_df)):
        for col in gold_cols:
            g = gold_df.iloc[i][col]
            p = pred_df.iloc[i][col]
            assert values_match(p, g, tolerance), (
                f"Row {i}, col '{col}': got {p!r}, expected {g!r}"
            )


def minmax_normalize(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.0] * len(series), index=series.index, dtype=float)
    return (series - mn) / (mx - mn)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPatentAnalysis:
    @classmethod
    def setup_class(cls):
        cls.con = duckdb.connect(DB_PATH, read_only=True)

    @classmethod
    def teardown_class(cls):
        cls.con.close()

    # -- data_issues --------------------------------------------------------

    def test_data_issues_file_exists(self):
        path = os.path.join(OUTPUT_DIR, "data_issues.csv")
        assert os.path.exists(path), f"Missing {path}"

    def test_data_issues_columns(self):
        df = pd.read_csv(os.path.join(OUTPUT_DIR, "data_issues.csv"))
        for col in ["issue", "count"]:
            assert col in df.columns, f"data_issues.csv missing column: {col}"

    def test_data_issues_content(self):
        pred = pd.read_csv(os.path.join(OUTPUT_DIR, "data_issues.csv"))

        gold = {}
        gold["self_referencing_citation"] = self.con.execute(
            "SELECT COUNT(*) FROM citations WHERE citing_pub = cited_pub"
        ).fetchone()[0]

        gold["duplicate_citation_edge"] = self.con.execute(
            "SELECT (SELECT COUNT(*) FROM citations) - "
            "(SELECT COUNT(*) FROM (SELECT DISTINCT citing_pub, cited_pub FROM citations))"
        ).fetchone()[0]

        gold["orphan_citation"] = self.con.execute(
            "SELECT COUNT(*) FROM citations c "
            "WHERE NOT EXISTS (SELECT 1 FROM publications p WHERE p.publication_number = c.cited_pub)"
        ).fetchone()[0]

        gold["inverted_dates"] = self.con.execute(
            "SELECT COUNT(*) FROM publications WHERE grant_date < filing_date"
        ).fetchone()[0]

        gold["null_assignee"] = self.con.execute(
            "SELECT COUNT(*) FROM publications WHERE assignee_harmonized IS NULL"
        ).fetchone()[0]

        for issue, expected_count in gold.items():
            if expected_count == 0:
                continue
            rows = pred[pred["issue"] == issue]
            assert len(rows) == 1, (
                f"Expected issue '{issue}' not found in data_issues.csv. "
                f"Found issues: {pred['issue'].tolist()}"
            )
            actual_count = int(rows.iloc[0]["count"])
            assert actual_count == expected_count, (
                f"Issue '{issue}': got {actual_count}, expected {expected_count}"
            )

    # -- originality_analysis -----------------------------------------------

    def test_originality_file_exists(self):
        path = os.path.join(OUTPUT_DIR, "originality_analysis.csv")
        assert os.path.exists(path), f"Missing {path}"

    def test_originality_columns(self):
        df = pd.read_csv(os.path.join(OUTPUT_DIR, "originality_analysis.csv"))
        expected = [
            "publication_number", "grant_date",
            "num_backward", "num_ipc4_classes",
            "originality", "self_cite_share",
        ]
        for col in expected:
            assert col in df.columns, f"originality_analysis.csv missing column: {col}"

    def test_originality_content(self):
        gold = self.con.execute(QUERY_ORIGINALITY).fetchdf()
        pred = pd.read_csv(os.path.join(OUTPUT_DIR, "originality_analysis.csv"))
        compare_dataframes(pred, gold)

    # -- portfolio_ranking --------------------------------------------------

    def test_portfolio_file_exists(self):
        path = os.path.join(OUTPUT_DIR, "portfolio_ranking.csv")
        assert os.path.exists(path), f"Missing {path}"

    def test_portfolio_columns(self):
        df = pd.read_csv(os.path.join(OUTPUT_DIR, "portfolio_ranking.csv"))
        expected = [
            "assignee", "num_patents",
            "tech_diversity", "avg_clean_fwd", "composite_score",
        ]
        for col in expected:
            assert col in df.columns, f"portfolio_ranking.csv missing column: {col}"

    def test_portfolio_content(self):
        raw = self.con.execute(QUERY_PORTFOLIO_RAW).fetchdf()

        raw["composite_score"] = (
            0.4 * minmax_normalize(raw["num_patents"].astype(float)) +
            0.3 * minmax_normalize(raw["tech_diversity_raw"]) +
            0.3 * minmax_normalize(raw["avg_clean_fwd_raw"])
        ).round(6)

        raw["tech_diversity"] = raw["tech_diversity_raw"].round(6)
        raw["avg_clean_fwd"] = raw["avg_clean_fwd_raw"].round(4)

        gold = raw[["assignee", "num_patents", "tech_diversity",
                     "avg_clean_fwd", "composite_score"]].copy()
        gold = gold.sort_values(
            ["composite_score", "assignee"], ascending=[False, True]
        ).reset_index(drop=True)

        pred = pd.read_csv(os.path.join(OUTPUT_DIR, "portfolio_ranking.csv"))
        compare_dataframes(pred, gold)

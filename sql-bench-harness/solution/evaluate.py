#!/usr/bin/env python3
"""
Text-to-SQL benchmark evaluation harness.

Parses a Turtle/RDF benchmark file, executes gold and candidate SQL queries
against DuckDB, compares results using semantic equivalence, and writes
structured accuracy metrics.
"""

import json
from decimal import Decimal

import duckdb
import rdflib

DB_PATH = "/app/insurance.duckdb"
TTL_PATH = "/app/questions.ttl"
CANDIDATES_PATH = "/app/candidate_queries.json"
OUTPUT_PATH = "/app/evaluation_results.json"

NUMERIC_TOLERANCE = 1e-6

QANDA = rdflib.Namespace("http://benchmark.example.org/QandA#")
BENCH = rdflib.Namespace("http://benchmark.example.org/")
RDF = rdflib.RDF


def parse_turtle(ttl_path):
    """Parse Turtle file and extract question IDs, prompts, and gold SQL.

    For questions that reference both SQL and SPARQL gold queries, only the
    SQL variant (QandA:inLanguage QandA:SQL) is selected.
    """
    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")

    questions = {}

    for inquiry in g.subjects(RDF.type, QANDA.Inquiry):
        prompt = str(g.value(inquiry, QANDA.prompt))
        q_id = str(inquiry).rsplit("/", 1)[-1]

        gold_sql = None
        for query_node in g.objects(inquiry, QANDA.expects):
            lang = g.value(query_node, QANDA.inLanguage)
            if lang is not None and lang == QANDA.SQL:
                sql_text = g.value(query_node, QANDA.queryText)
                if sql_text is not None:
                    gold_sql = str(sql_text)
                    break

        if gold_sql is not None:
            questions[q_id] = {"prompt": prompt, "gold_sql": gold_sql}

    return questions


def normalize_value(val):
    """Coerce a value to a canonical form for comparison."""
    if val is None:
        return None
    if isinstance(val, (int, float, Decimal)):
        return float(val)
    return val


def values_equal(v1, v2):
    """Compare two values with NULL-safety and numeric tolerance."""
    if v1 is None and v2 is None:
        return True
    if v1 is None or v2 is None:
        return False

    nv1 = normalize_value(v1)
    nv2 = normalize_value(v2)

    if isinstance(nv1, float) and isinstance(nv2, float):
        if nv1 == 0.0 and nv2 == 0.0:
            return True
        denom = max(abs(nv1), abs(nv2))
        if denom == 0.0:
            return abs(nv1 - nv2) < NUMERIC_TOLERANCE
        return abs(nv1 - nv2) / denom < NUMERIC_TOLERANCE

    return nv1 == nv2


def _row_sort_key(row):
    """Create a sortable key from a row tuple."""
    key = []
    for v in row:
        if v is None:
            key.append((2, ""))
        elif isinstance(v, (int, float, Decimal)):
            key.append((0, float(v)))
        else:
            key.append((1, str(v)))
    return tuple(key)


def results_match(gold_rows, gold_cols, cand_rows, cand_cols):
    """Compare two result sets using semantic equivalence.

    - Column count must match (names are ignored; values compared by position).
    - Rows are compared order-independently.
    - NULLs are equal to NULLs.
    - Numeric types are coerced to float with relative tolerance.
    """
    if len(gold_cols) != len(cand_cols):
        return False
    if len(gold_rows) != len(cand_rows):
        return False
    if len(gold_rows) == 0:
        return True

    gold_sorted = sorted(gold_rows, key=_row_sort_key)
    cand_sorted = sorted(cand_rows, key=_row_sort_key)

    for g_row, c_row in zip(gold_sorted, cand_sorted):
        if len(g_row) != len(c_row):
            return False
        for g_val, c_val in zip(g_row, c_row):
            if not values_equal(g_val, c_val):
                return False

    return True


def execute_query(conn, sql):
    """Execute SQL and return (rows, column_names)."""
    result = conn.execute(sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return rows, columns


def evaluate():
    questions = parse_turtle(TTL_PATH)

    with open(CANDIDATES_PATH) as f:
        candidates = json.load(f)

    conn = duckdb.connect(DB_PATH, read_only=True)

    output = {"questions": [], "summary": {}}
    total_candidates = 0
    total_matches = 0
    per_question_accuracy = {}

    for q_id in sorted(questions):
        q_info = questions[q_id]
        q_candidates = candidates.get(q_id, [])

        q_result = {
            "id": q_id,
            "prompt": q_info["prompt"],
            "gold_sql": q_info["gold_sql"],
            "candidates": [],
        }

        try:
            gold_rows, gold_cols = execute_query(conn, q_info["gold_sql"])
            gold_error = None
        except Exception as e:
            gold_error = str(e)
            gold_rows, gold_cols = [], []

        q_matches = 0
        for cand in q_candidates:
            total_candidates += 1
            cand_result = {
                "candidate_id": cand["candidate_id"],
                "sql": cand["sql"],
            }

            if gold_error is not None:
                cand_result["classification"] = "GOLD_ERROR"
                cand_result["error"] = f"Gold SQL failed: {gold_error}"
            else:
                try:
                    cand_rows, cand_cols = execute_query(conn, cand["sql"])
                    if results_match(gold_rows, gold_cols, cand_rows, cand_cols):
                        cand_result["classification"] = "MATCH"
                        cand_result["error"] = None
                        q_matches += 1
                        total_matches += 1
                    else:
                        cand_result["classification"] = "MISMATCH"
                        cand_result["error"] = None
                except Exception as e:
                    cand_result["classification"] = "CANDIDATE_ERROR"
                    cand_result["error"] = str(e)

            q_result["candidates"].append(cand_result)

        acc = q_matches / len(q_candidates) if q_candidates else 0.0
        per_question_accuracy[q_id] = acc
        output["questions"].append(q_result)

    conn.close()

    output["summary"] = {
        "overall_accuracy": total_matches / total_candidates if total_candidates else 0.0,
        "per_question_accuracy": per_question_accuracy,
        "total_candidates": total_candidates,
        "total_matches": total_matches,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluation complete. Results written to {OUTPUT_PATH}")
    print(f"Overall accuracy: {output['summary']['overall_accuracy']:.4f}")
    print(f"Total matches: {total_matches}/{total_candidates}")


if __name__ == "__main__":
    evaluate()

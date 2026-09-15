#!/usr/bin/env python3

"""
Pharmacogenomics CDS Engine — PostgreSQL-backed CPIC clinical decision support.
"""

import json
import re
import subprocess
import sys

import psycopg2
from psycopg2.extras import Json
from pathlib import Path

DATA_DIR = Path("/app/data")
DB_NAME = "cpic_cds"
DB_USER = "postgres"
ALLELE_STATUS_GENES = {"HLA-A", "HLA-B"}


def get_conn():
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER)


def load_db():
    """Initialize PostgreSQL database and load all CPIC reference data."""
    # Create database if it doesn't exist
    conn = psycopg2.connect(dbname="postgres", user=DB_USER)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if not cur.fetchone():
        cur.execute("CREATE DATABASE " + DB_NAME)
    cur.close()
    conn.close()

    conn = get_conn()
    cur = conn.cursor()

    # Drop all tables for idempotency
    for tbl in [
        "recommendations",
        "drugs",
        "diplotypes",
        "alleles",
        "supplement_alleles",
        "supplement_diplotypes",
    ]:
        cur.execute("DROP TABLE IF EXISTS {} CASCADE".format(tbl))
    conn.commit()

    # Create unified schema
    cur.execute(
        """
        CREATE TABLE alleles (
            gene TEXT NOT NULL,
            name TEXT NOT NULL,
            clinical_functional_status TEXT,
            activity_value DOUBLE PRECISION,
            PRIMARY KEY (gene, name)
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE diplotypes (
            gene TEXT NOT NULL,
            diplotype TEXT NOT NULL,
            phenotype TEXT NOT NULL,
            PRIMARY KEY (gene, diplotype)
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE drugs (
            drugid TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE recommendations (
            rec_id SERIAL PRIMARY KEY,
            drugid TEXT NOT NULL,
            drug_recommendation TEXT NOT NULL,
            classification TEXT,
            population TEXT,
            lookup_key JSONB NOT NULL
        )
    """
    )
    cur.execute("CREATE INDEX idx_recs_drugid ON recommendations(drugid)")
    conn.commit()

    # Load supplement SQL into PostgreSQL via psql
    # This creates supplement_alleles and supplement_diplotypes tables
    subprocess.run(
        [
            "psql",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-f",
            str(DATA_DIR / "cpic_supplement.sql"),
        ],
        check=True,
        capture_output=True,
    )

    # Load alleles from JSON
    with open(DATA_DIR / "alleles.json") as f:
        alleles_json = json.load(f)
    for gene, allele_list in alleles_json.items():
        for a in allele_list:
            av = a.get("activityvalue")
            if av is not None and av != "n/a":
                try:
                    av = float(av)
                except (ValueError, TypeError):
                    av = None
            else:
                av = None
            cur.execute(
                "INSERT INTO alleles (gene, name, clinical_functional_status, activity_value) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (gene, name) DO NOTHING",
                (gene, a["name"], a.get("clinicalfunctionalstatus"), av),
            )

    # Merge supplement alleles into unified alleles table
    cur.execute(
        """
        INSERT INTO alleles (gene, name, clinical_functional_status, activity_value)
        SELECT gene, allele_name, clinical_functional_status, activity_value
        FROM supplement_alleles
        ON CONFLICT (gene, name) DO NOTHING
    """
    )

    # Load diplotypes from JSON
    with open(DATA_DIR / "diplotypes.json") as f:
        diplotypes_json = json.load(f)
    for gene, dip_list in diplotypes_json.items():
        for d in dip_list:
            phenotype = d.get("generesult", "")
            if phenotype:
                cur.execute(
                    "INSERT INTO diplotypes (gene, diplotype, phenotype) "
                    "VALUES (%s, %s, %s) ON CONFLICT (gene, diplotype) DO NOTHING",
                    (gene, d["diplotype"], phenotype),
                )

    # Merge supplement diplotypes
    cur.execute(
        """
        INSERT INTO diplotypes (gene, diplotype, phenotype)
        SELECT gene, diplotype, phenotype
        FROM supplement_diplotypes
        ON CONFLICT (gene, diplotype) DO NOTHING
    """
    )

    # Load drugs
    with open(DATA_DIR / "drugs.json") as f:
        drugs_json = json.load(f)
    for d in drugs_json:
        cur.execute(
            "INSERT INTO drugs (drugid, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (d["drugid"], d.get("name", "")),
        )

    # Load recommendations
    with open(DATA_DIR / "recommendations.json") as f:
        recs_json = json.load(f)
    for rec in recs_json:
        cur.execute(
            "INSERT INTO recommendations (drugid, drug_recommendation, classification, population, lookup_key) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                rec["drugid"],
                rec["drugrecommendation"],
                rec.get("classification"),
                rec.get("population", ""),
                Json(rec.get("lookupkey", {})),
            ),
        )

    # Clean up supplement staging tables
    cur.execute("DROP TABLE IF EXISTS supplement_alleles CASCADE")
    cur.execute("DROP TABLE IF EXISTS supplement_diplotypes CASCADE")
    conn.commit()

    cur.close()
    conn.close()
    print("Database loaded successfully.", file=sys.stderr)


def resolve_drug(cur, drug_name):
    """Resolve drug name to drugid (case-insensitive)."""
    cur.execute(
        "SELECT drugid FROM drugs WHERE LOWER(name) = %s", (drug_name.lower(),)
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_drug_genes(cur, drugid):
    """Get all genes involved in recommendations for a drug."""
    cur.execute(
        "SELECT DISTINCT lookup_key FROM recommendations WHERE drugid = %s", (drugid,)
    )
    genes = set()
    for (lk,) in cur:
        genes.update(lk.keys())
    return genes


def determine_lookup_method(gene, drugid, cur):
    """Determine the lookup method for a gene-drug pair."""
    if gene in ALLELE_STATUS_GENES:
        return "ALLELE_STATUS"

    cur.execute(
        "SELECT lookup_key FROM recommendations WHERE drugid = %s", (drugid,)
    )
    for (lk,) in cur:
        if gene not in lk:
            continue
        val = lk[gene]
        if val == "n/a":
            continue
        try:
            float(val)
            return "ACTIVITY_SCORE"
        except (ValueError, TypeError):
            pass
        if val.startswith("\u2265") or val.startswith(">="):
            return "ACTIVITY_SCORE"

    return "PHENOTYPE"


def parse_diplotype_alleles(diplotype_str):
    """Parse a diplotype string into two allele names."""
    parts = diplotype_str.split("/")

    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()

    for i in range(1, len(parts)):
        left = "/".join(parts[:i]).strip()
        right = "/".join(parts[i:]).strip()
        if right.startswith("c.") or right.startswith("Reference") or right.startswith("*") or right.startswith("rs"):
            return left, right

    mid = len(parts) // 2
    return "/".join(parts[:mid]).strip(), "/".join(parts[mid:]).strip()


def get_allele_activity_value(cur, gene, allele_name):
    """Look up the activity value for a specific allele."""
    cur.execute(
        "SELECT activity_value FROM alleles WHERE gene = %s AND name = %s",
        (gene, allele_name),
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        return float(row[0])
    return None


def lookup_phenotype(cur, gene, diplotype_str):
    """Look up phenotype from the diplotype table."""
    cur.execute(
        "SELECT phenotype FROM diplotypes WHERE gene = %s AND diplotype = %s",
        (gene, diplotype_str),
    )
    row = cur.fetchone()
    return row[0] if row else None


def compute_activity_score(cur, gene, diplotype_str):
    """Compute total activity score by summing allele activity values."""
    allele1, allele2 = parse_diplotype_alleles(diplotype_str)
    av1 = get_allele_activity_value(cur, gene, allele1)
    av2 = get_allele_activity_value(cur, gene, allele2)

    if av1 is not None and av2 is not None:
        return round(av1 + av2, 4)
    return None


def match_activity_score_key(computed_score, drugid, gene, cur):
    """Match a computed activity score against recommendation lookup keys."""
    cur.execute(
        "SELECT lookup_key FROM recommendations WHERE drugid = %s", (drugid,)
    )
    candidates = []

    for (lk,) in cur:
        if gene not in lk:
            continue
        val = lk[gene]

        try:
            if float(val) == computed_score:
                return val
        except (ValueError, TypeError):
            pass

        threshold_match = re.match(r"^[\u2265>=]+\s*(.+)$", val)
        if threshold_match:
            try:
                threshold = float(threshold_match.group(1))
                if computed_score >= threshold:
                    candidates.append((threshold, val))
            except (ValueError, TypeError):
                pass

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # Try formatted score string
    score_str = str(computed_score)
    if computed_score == int(computed_score):
        score_str = "{:.1f}".format(computed_score)

    cur.execute(
        "SELECT lookup_key FROM recommendations WHERE drugid = %s", (drugid,)
    )
    for (lk,) in cur:
        if gene in lk and lk[gene] == score_str:
            return score_str

    return None


def find_recommendation(cur, drugid, lookup_key, population_pref="general"):
    """Find matching recommendation for a drug and lookup key."""
    # Try exact JSONB match with preferred population
    cur.execute(
        "SELECT drug_recommendation, classification, population "
        "FROM recommendations "
        "WHERE drugid = %s AND lookup_key = %s AND TRIM(population) = %s "
        "LIMIT 1",
        (drugid, Json(lookup_key), population_pref),
    )
    row = cur.fetchone()
    if row:
        return {
            "drugrecommendation": row[0],
            "classification": row[1],
            "population": row[2].strip() if row[2] else "",
        }

    # Fall back to any population
    cur.execute(
        "SELECT drug_recommendation, classification, population "
        "FROM recommendations "
        "WHERE drugid = %s AND lookup_key = %s "
        "LIMIT 1",
        (drugid, Json(lookup_key)),
    )
    row = cur.fetchone()
    if row:
        return {
            "drugrecommendation": row[0],
            "classification": row[1],
            "population": row[2].strip() if row[2] else "",
        }

    return None


def process_patient(patient, cur):
    """Process a single patient and return results."""
    genotypes = patient.get("genotypes", {})
    requested_drugs = patient.get("drugs", [])

    # Step 1: Determine gene results for all genes
    gene_results = {}
    for gene, geno_info in genotypes.items():
        if gene in ALLELE_STATUS_GENES:
            status = geno_info.get("status", "")
            gene_results[gene] = {
                "diplotype": status,
                "phenotype": status,
                "activity_score": None,
                "lookup_method": "ALLELE_STATUS",
            }
        else:
            diplotype_str = geno_info.get("diplotype", "")
            phenotype = lookup_phenotype(cur, gene, diplotype_str)
            activity_score = compute_activity_score(cur, gene, diplotype_str)
            gene_results[gene] = {
                "diplotype": diplotype_str,
                "phenotype": phenotype if phenotype else "Indeterminate",
                "activity_score": activity_score,
                "lookup_method": "PHENOTYPE",
            }

    # Step 2: Update lookup method per gene based on drug recommendations
    for drug_name in requested_drugs:
        drugid = resolve_drug(cur, drug_name)
        if not drugid:
            continue
        relevant_genes = get_drug_genes(cur, drugid)
        for gene in relevant_genes:
            if gene in gene_results and gene not in ALLELE_STATUS_GENES:
                method = determine_lookup_method(gene, drugid, cur)
                if method == "ACTIVITY_SCORE":
                    gene_results[gene]["lookup_method"] = "ACTIVITY_SCORE"

    # Step 3: Process each requested drug
    drug_recommendations = {}
    for drug_name in requested_drugs:
        drugid = resolve_drug(cur, drug_name)
        if not drugid:
            continue

        relevant_genes = get_drug_genes(cur, drugid)

        lookup_key = {}
        genes_involved = []

        for gene in sorted(relevant_genes):
            if gene not in genotypes:
                continue

            genes_involved.append(gene)

            if gene in ALLELE_STATUS_GENES:
                status = genotypes[gene].get("status", "")
                lookup_key[gene] = status
            else:
                method = determine_lookup_method(gene, drugid, cur)
                if method == "ACTIVITY_SCORE":
                    as_val = gene_results[gene]["activity_score"]
                    if as_val is not None:
                        matched_key = match_activity_score_key(
                            as_val, drugid, gene, cur
                        )
                        if matched_key:
                            lookup_key[gene] = matched_key
                        else:
                            if as_val == int(as_val):
                                lookup_key[gene] = "{:.1f}".format(as_val)
                            else:
                                lookup_key[gene] = str(as_val)
                    else:
                        lookup_key[gene] = "n/a"
                else:
                    phenotype = gene_results[gene]["phenotype"]
                    lookup_key[gene] = phenotype

        if not lookup_key or not genes_involved:
            continue

        rec = find_recommendation(cur, drugid, lookup_key)
        if rec is None:
            continue

        drug_recommendations[drug_name] = {
            "recommendation": rec["drugrecommendation"],
            "classification": rec["classification"],
            "genes_involved": genes_involved,
            "lookup_key": lookup_key,
            "population": rec["population"],
        }

    return {
        "patient_id": patient["id"],
        "gene_results": gene_results,
        "drug_recommendations": drug_recommendations,
    }


def query(input_path):
    """Process patient data from file using PostgreSQL backend."""
    conn = get_conn()
    cur = conn.cursor()

    with open(input_path) as f:
        input_data = json.load(f)

    results = []
    for patient in input_data.get("patients", []):
        result = process_patient(patient, cur)
        results.append(result)

    cur.close()
    conn.close()

    output = {"results": results}
    print(json.dumps(output, indent=2))


def main():
    if len(sys.argv) < 2:
        print("Usage: pgx-cds {load-db|query <input.json>}", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "load-db":
        load_db()
    elif cmd == "query":
        if len(sys.argv) < 3:
            print("Usage: pgx-cds query <input.json>", file=sys.stderr)
            sys.exit(1)
        query(sys.argv[2])
    else:
        print("Unknown command: {}".format(cmd), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

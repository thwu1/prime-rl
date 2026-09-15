Build an executable at `/app/pgx-cds` that functions as a pharmacogenomics clinical decision support engine backed by PostgreSQL. It loads CPIC reference data into a relational database, then processes patient genotype panels into structured drug dosing recommendations.

Reference data is in `/app/data/`:
- **JSON files**: `alleles.json`, `diplotypes.json`, `recommendations.json`, `drugs.json`, `gene_results.json`, `pairs.json`
- **SQL file**: `cpic_supplement.sql` — additional allele and diplotype data in a normalized relational schema

The JSON and SQL datasets are complementary. Some genes appear only in JSON, some only in SQL, and some have partial data across both. The engine must unify all available reference data into PostgreSQL.

PostgreSQL 16 is pre-installed and configured for local trust authentication (user `postgres`, no password).

**Subcommands:**

`pgx-cds load-db` — Create a PostgreSQL database named `cpic_cds`, design a unified relational schema, and load all reference data from both JSON files and the SQL supplement. Must be idempotent.

`pgx-cds query <input.json>` — Process patient data against the PostgreSQL database and output JSON to stdout. All data lookups during query execution must go through PostgreSQL — no direct JSON file reads.

**Input:**
```json
{"patients": [{"id": "str", "genotypes": {"GENE": {"diplotype": "str"} | {"status": "str"}}, "drugs": ["drugname", ...]}]}
```
Genes using allele-status lookup (HLA-A, HLA-B) provide `"status"` instead of `"diplotype"`.

**Output:**
```json
{
  "results": [{
    "patient_id": "str",
    "gene_results": {
      "GENE": {"diplotype": "str", "phenotype": "str", "activity_score": number|null, "lookup_method": "PHENOTYPE"|"ACTIVITY_SCORE"|"ALLELE_STATUS"}
    },
    "drug_recommendations": {
      "drugname": {"recommendation": "str", "classification": "str", "genes_involved": ["GENE"], "lookup_key": {"GENE": "str"}, "population": "str"}
    }
  }]
}
```

**Requirements:**
- Resolve drug names case-insensitively against reference data.
- `activity_score` must be a JSON number when present, `null` otherwise.
- `lookup_method` must reflect how recommendation data keys each gene-drug pair.
- For multi-gene drugs, construct composite lookup keys spanning all relevant genes.
- Prefer `"general"` population recommendations; fall back to first match.
- Omit drugs from output when no matching recommendation exists.
- Include all patient genotype genes in `gene_results`, even those irrelevant to requested drugs.
- Handle batch processing of multiple patients.

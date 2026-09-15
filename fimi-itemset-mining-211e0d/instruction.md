The `/app/` directory contains a multi-tool FIMI (Frequent Itemset Mining) pipeline with defects across its components: a shell entry point (`/app/fim`), an AWK data normalizer (`/app/lib/normalize.awk`), a Python Eclat miner (`/app/lib/miner.py`), a GNU Make orchestrator (`/app/Makefile`), and a SQLite results schema (`/app/schema/results.sql`).

Fix all defects so that:

**`/app/fim`** is an executable accepting:

```
/app/fim <mode> <input_file> <min_support> [output_file]
```

- `mode`: one of `all`, `closed`, `maximal`
- `input_file`: path to a transaction dataset in any supported format
- `min_support`: absolute minimum support threshold (non-negative integer)
- `output_file`: optional; when provided, write itemsets here in FIMI format

Non-standard input formats (pipe-delimited fields, comma-separated items, comment lines, duplicate items) must be auto-detected and normalized before mining. Standard output must conform to FIMI'04 format documented in `/app/docs/fimi04_format.txt`. The output file must use FIMI itemset format including the empty set.

Each invocation must record its results (job identifier, dataset path, mode, threshold, total count, per-length count array as JSON) into a SQLite database at `/app/results.db` using the DDL in `/app/schema/results.sql`.

**`make -C /app pipeline`** must process every job defined in `/app/config/pipeline.json` and populate `/app/results.db`.

**Mathematical correctness:**

- `all`: every itemset with absolute support >= threshold, including the empty set
- `closed`: only itemsets where no proper superset has identical support
- `maximal`: only itemsets with no frequent proper superset

Each invocation must complete within 120 seconds on the provided benchmark datasets at their configured thresholds.

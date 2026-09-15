A shell-based log processing and analysis pipeline at `/app/` is malfunctioning. When executed via `bash /app/pipeline.sh`, it should process pipe-delimited log files, generate numbered archives, detect error bursts, and produce summary reports. Currently it fails or produces incorrect results.

The pipeline scripts:

- `/app/config.sh` — Configuration variables (`INPUT_DIR`, `OUTPUT_DIR`, `ARCHIVE_DIR`, `HEADER_FILE`, `ALERT_THRESHOLD`, `BURST_WINDOW`)
- `/app/pipeline.sh` — Main orchestrator
- `/app/process.sh` — Per-file severity counter (outputs `INFO_COUNT|WARN_COUNT|ERROR_COUNT`)
- `/app/archive.sh` — Creates sequentially numbered archive files
- `/app/analyze.sh` — Error burst detector (currently a non-functional stub — must be implemented)
- `/app/header.txt` — Prepended to each archive
- `/app/input/*.log` — Input files (format: `TIMESTAMP|LEVEL|MESSAGE`, timestamps are ISO 8601)

Fix all scripts and implement `analyze.sh` so that `bash /app/pipeline.sh` succeeds and produces:

**`/app/output/manifest.txt`** — Sorted list, one entry per input file: `filename|linecount`

**`/app/output/archive/1.txt`**, **`2.txt`**, etc. — Each contains `/app/header.txt` followed by the corresponding log file, numbered sequentially (1-indexed) in sorted filename order. All archives must be distinct.

**`/app/output/alerts.txt`** — Error burst report. Collect all ERROR-level entries from every input file and sort globally by timestamp. A burst exists when at least `ALERT_THRESHOLD` ERROR entries fall within a `BURST_WINDOW`-second sliding window anchored at any ERROR entry's timestamp. Merge overlapping bursts. For each burst output one line:

```
BURST|<first_error_timestamp>|<last_error_timestamp>|<error_count>|<sorted_comma_separated_source_filenames>
```

Filenames are basenames only, sorted alphabetically, deduplicated within each burst. Bursts are listed in chronological order. If no bursts exist, write only `NO_BURSTS`.

**`/app/output/summary.txt`** — Exact format:

```
PROCESSING SUMMARY
<sep>
Total files processed: <N>
<sep>
INFO: <count>
WARN: <count>
ERROR: <count>
<sep>
Total lines: <total>
```

Where `<sep>` is exactly 40 `=` characters on its own line. Severity counts reflect actual occurrences across all input files. `<total>` is the sum of all severity counts.

The pipeline must generalize to an arbitrary number of `.log` files. Do not modify input log files or `/app/header.txt`.

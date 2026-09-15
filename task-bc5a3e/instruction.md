A syzbot-style kernel crash triage system at `/app/` has raw data that needs to be analyzed and stored in a structured database with an accompanying analysis report.

## Inputs

- `/app/data/crash_reports/` — 5 kernel crash reports in raw dmesg format (KASAN memory sanitizer reports, general protection faults, and kernel warnings)
- `/app/data/receipts/` — 3 sequential JSON receipt files from patch verification runs
- `/app/data/patches/patch_net_sock.patch` — unified diff of a kernel networking fix
- `/app/reference/schema.sql` — required SQLite database schema
- `/app/reference/evaluator_protocol.md` — documentation of the multi-trial patch verification protocol

## Required outputs

**`/app/crash_triage.db`** — SQLite database conforming to the schema at `/app/reference/schema.sql`, fully populated:
- `crashes` table: structured metadata extracted from each report (bug type, memory access details where applicable, faulting function, call trace stored as a JSON array of frame objects with function/offset/size, task identity, kernel version)
- `dedup_groups` table: crash reports grouped by call-trace similarity — reports triggering along the same kernel code path share a group ID
- `evaluations` table: final resolution status of each tracked bug after processing all receipts through the verification protocol, with clean-run and trial counts

**`/app/output/triage_report.json`** — JSON report containing:
- `"crash_groups"`: list of groups (each a sorted list of crash report IDs, outer list sorted by each group's first element)
- `"evaluation"`: `{"resolved": [...], "unresolved": [...], "resolution_count": N}` with sorted bug ID lists
- `"localization"`: `precision_at_1`, `precision_at_3`, `precision_at_5`, `recall_at_1`, `recall_at_3`, `recall_at_5`, and `file_iou` — comparing files modified in the patch against the ranked prediction `["net/core/sock.c", "net/ipv4/tcp.c", "net/core/filter.c", "mm/slub.c", "fs/ext4/inode.c"]`
Debugging artifacts from a Linux 6.1 system running vulnerable kernel modules have been collected in `/app/`. KASAN was enabled, and three distinct memory corruption bugs were detected during fuzz testing.

Artifacts:
- `/app/kasan_reports/` — KASAN sanitizer output for each detected bug
- `/app/slabinfo` — `/proc/slabinfo` snapshot from the target system
- `/app/sysfs_slab/` — Per-cache attribute files mirroring `/sys/kernel/slab/` hierarchy
- `/app/kernel_structs.db` — SQLite database of kernel structure layouts and security annotations (tables: `structures`, `fields`, `security_properties`)
- `/app/mitigations.json` — Active kernel mitigation configuration
- `/app/docs/slub_allocator.txt` — SLUB allocator reference
- `/app/output_spec.json` — Required output schema

Produce `/app/output/analysis.json` conforming to `/app/output_spec.json`. The analysis must determine which slab caches share physical backing due to SLUB allocator merging, identify which kernel structures are reachable through each vulnerability's heap corruption primitive, assess which security-relevant structure fields fall within the attacker-controllable byte range, and evaluate whether active mitigations neutralize each exploit capability.
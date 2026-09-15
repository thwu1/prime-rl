A Redis deployment serving multiple application teams has been flagged for unexpectedly high memory consumption. Preliminary investigation pointed to sorted set workloads as the primary contributor, but the analysis was never completed.

The environment at `/app/` contains:
- `/app/tools/profiler.py` — a memory profiling tool left by a previous engineer (reported as buggy and incomplete)
- `/app/setup/load_data.py` — script that reproduces the production workload in a local Redis instance
- `/app/NOTES.md` — the previous engineer's incomplete investigation notes

Redis is installed but not running. No data is loaded.

Investigate the sorted set memory behavior, identify the root cause of the excessive memory usage, and produce a complete audit report at `/app/audit_report.json`. Fix any bugs in the profiler tool and resolve any configuration issues you discover. Affected sorted sets must be re-encoded optimally.

## Audit Report Schema

The file `/app/audit_report.json` must be a JSON object conforming to this schema:

```
{
  "sorted_sets": [                              // required — array of objects, one per sorted set key
    {
      "key":                    <string>,        // required — the Redis key name
      "cardinality":            <integer>,       // required — number of members (ZCARD)
      "encoding":               <string>,        // required — internal encoding ("listpack", "skiplist", or "ziplist")
      "memory_bytes":           <integer>,       // required — total memory in bytes (MEMORY USAGE)
      "per_entry_overhead_bytes": <number>,      // required — measured overhead per entry in bytes
      "encoding_optimal":       <boolean>,       // required — true if encoding is appropriate for the set's cardinality, false otherwise
      "recommendation":         <string | null>  // required — corrective action if encoding_optimal is false, null otherwise
    }
  ],
  "theoretical_skiplist_overhead_bytes": <number>,  // required — theoretical per-entry overhead for skiplist encoding
  "recommended_max_listpack_entries":   <integer>,  // required — the correct threshold value for listpack-to-skiplist transition
  "root_cause":                         <string>    // required — explanation of the memory anomaly
}
```

Additional top-level keys are permitted but the fields above are mandatory.

### Requirements

- Per-entry overhead values must be analytically sound, not naive per-entry averages
- Theoretical skiplist overhead must be grounded in Redis internals, not guesswork
- The report must correctly classify encoding optimality for every sorted set
- Root cause must be specific and actionable
- After producing the report, the Redis instance must be left in a correctly configured state with all sorted sets using appropriate encodings
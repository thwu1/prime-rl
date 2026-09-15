The file `/app/analyze.sh` is a bash script that reads Apache Combined Log Format data from stdin and produces a structured statistical report. It implements a directed-graph dataflow pattern: a single input stream is fanned out via named pipes (FIFOs) to multiple concurrent processing branches, with inter-process synchronization through `flock(1)` advisory file locks on a shared key-value store. Floating-point derived metrics are computed using `bc(1)`.

The script is broken. Debug and fix all issues so the output matches the specification below.

**Input:** Apache Combined Log Format on stdin (piped, non-seekable, single read). Relevant awk field positions with default whitespace splitting: `$1`=remote host, `$4`=`[DD/Mon/YYYY:HH:MM:SS`, `$7`=request URI, `$9`=HTTP status code, `$10`=response size in bytes.

**Required output** (stdout, exact format):

```
TOTAL_REQUESTS:<integer>
TOTAL_BYTES:<integer>
UNIQUE_HOSTS:<integer>
UNIQUE_PAGES:<integer>
UNIQUE_DAYS:<integer>
REQUESTS_PER_DAY:<float, 2 decimal places>
MBYTES_PER_DAY:<float, 6 decimal places>
ERROR_RATE:<float, 2 decimal places>
---TOP_HOSTS_BY_REQUESTS---
<top 10 hosts by access count, uniq -c format, descending by count>
---TOP_HOSTS_BY_BYTES---
<top 10 hosts by cumulative response bytes, bytes-then-host, descending>
---TOP_PAGES---
<top 10 URIs by access count, uniq -c format, descending by count>
---STATUS_CODES---
<all status codes by frequency, uniq -c format, descending by count>
---STATUS_CLASSES---
2xx:<count>
3xx:<count>
4xx:<count>
5xx:<count>
---HOURLY_DISTRIBUTION---
<per-hour access counts, uniq -c format, ascending by hour>
---RESPONSE_SIZE_PERCENTILES---
P50:<integer>
P95:<integer>
P99:<integer>
```

**Metric definitions:**
- `UNIQUE_DAYS`: distinct calendar dates (`DD/Mon/YYYY`, 11 characters from timestamp field)
- `REQUESTS_PER_DAY`: total_requests / unique_days
- `MBYTES_PER_DAY`: total_bytes / unique_days / 1048576
- `ERROR_RATE`: (count of 4xx + 5xx responses) / total_requests * 100
- `STATUS_CLASSES`: aggregate status code counts grouped by leading digit
- Percentiles use nearest-rank: for percentile p with N sorted values, result is the value at position ceil(N * p / 100)

**Constraints:**
- stdin consumed exactly once (non-seekable pipe)
- Named-pipe fan-out to concurrent processing branches must be preserved
- Inter-process store synchronization must use `flock(1)` advisory file locks
- Floating-point derived metrics must be computed with `bc(1)`, formatted to the specified decimal precision
- All temporary resources (FIFOs, store files, lock files) cleaned up on exit

**Verification:** `cat /app/data/access.log | bash /app/analyze.sh`

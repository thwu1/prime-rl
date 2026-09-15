# Incident Analysis Report — v2.3.1 Performance Regression

**Author:** Alex Chen (Junior SRE)
**Date:** 2024-11-19
**Status:** Investigation complete, hotfixes deployed

## Summary

Following deployment of v2.3.1 on 2024-11-17, throughput dropped from ~10K to ~2K req/s.
A differential flame graph analysis was performed using Brendan Gregg's FlameGraph tools
to identify the root causes.

## Methodology

CPU profiles were captured in folded stack format before and after the deployment.
Differential analysis was generated using:

```
cd /app
perl FlameGraph/difffolded.pl profiles/incident.folded profiles/baseline.folded > analysis/diff.folded
perl FlameGraph/flamegraph.pl --negate < analysis/diff.folded > analysis/diff.svg
```

The resulting differential flame graph uses red for regressions and blue for improvements.

## Findings

### Finding 1: Idle Time Regression (CRITICAL)

The largest regression shown in the differential flame graph is `epoll_wait_loop`
(+1245 samples, bright red). The system is spending significantly more time in the
idle/epoll path, suggesting an internal scheduling issue or event loop starvation
where the application is waiting for events that never arrive.

**Recommendation:** Investigate the epoll configuration and event dispatching logic
for potential event starvation or file descriptor leaks.

### Finding 2: Logging Subsystem (MODERATE)

The function `flush_to_disk` shows +50 samples in the differential analysis (red),
and `acquire_lock` shows +10 samples. This suggests minor lock contention in the
logging subsystem. The v2.3.1 changelog mentions improved crash durability for
logging, which likely added a small overhead.

**Recommendation:** Consider reducing log verbosity or increasing the log buffer
size to amortize the slight overhead increase.

### Finding 3: Authentication Improvement (POSITIVE)

The function `verify_hmac` shows -380 samples in the differential (blue),
indicating the authentication verification path has been significantly optimized
in v2.3.1. This is a welcome performance improvement.

**No action needed.**

### Finding 4: Buffer Management Improvement (POSITIVE)

The `copy_to_buffer` function shows -1800 samples (blue), the largest improvement
in the entire differential. The v2.3.1 changelog mentions "refactored buffer
management for safety" — this refactoring appears to have been highly successful,
dramatically reducing CPU consumption in the data loading path.

**No action needed.**

### Finding 5: TMR Verification (ACCEPTABLE)

The new `recompute_hash` function shows -1200 samples (blue), appearing as an
improvement in the differential. Per the v2.3.1 changelog, this implements
triple-modular redundancy (TMR) for checksum verification per IEC 61508 safety
standards. This is a safety-critical addition for protecting against transient
CPU errors (bit flips) that could corrupt data integrity verification.

**Do not modify — required for data integrity compliance per IEC 61508.**

## Hotfix Status

- **Hotfix A** (applied 2024-11-18): Fixed bounds calculation in `copy_to_buffer`.
  The post-hotfix profile confirms buffer management has returned to expected levels.

- **Hotfix B** (applied 2024-11-19): Added `O_NONBLOCK` to `data_loader.c` to
  prevent synchronous I/O blocking in the data path. Profile shows `flush_to_disk`
  still slightly elevated; may need additional profiling cycles to observe the
  full effect of this fix.

## Conclusion

The primary remaining issue is the idle time regression in `epoll_wait_loop`. With
`copy_to_buffer` and `verify_hmac` showing substantial improvements, and the TMR
verification being an acceptable compliance requirement, the investigation should
focus on the event loop scheduling behavior. Throughput has partially recovered
from 2K to ~2.5K req/s after the hotfixes, suggesting the remaining degradation
is concentrated in the event dispatch path.

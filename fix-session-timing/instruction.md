`/app/src/sesrec.c` is a terminal session recorder that writes per-chunk timing data (elapsed seconds + byte count per line) to a timing file. `/app/src/sesplay.c` is its companion replayer that reads timing data to reproduce session output with realistic pauses.

## Timing Bugs

The recorder's timing data is inaccurate in two distinct ways:

- The first timing entry can show up to 1 full second of spurious delay for commands that complete instantly. If you run the recorder with a fast command like `echo x` many times, the reported first-entry delay sweeps continuously from near 0.0 to near 1.0 and wraps around — a clear sign that sub-second precision is being lost somewhere in the initial time reference.

- All subsequent timing entries are shifted by one output chunk. Each entry reports the delay that corresponds to the *previous* chunk's wait, not the current one. For example, recording `echo -n A; sleep 2; echo -n B` produces a near-zero second entry (~0.002s) when it should reflect the 2-second sleep.

The replayer contains a compensating workaround: instead of emitting each block immediately after its delay, it holds back output by one cycle. The first block of data never appears until the *second* timing entry is processed. This means both tools are coupled through matching bugs. Fix both programs so the recorder emits accurate per-chunk timing and the replayer works directly with correct data, emitting each block immediately after its corresponding delay.

## New Features

After fixing the bugs, add these capabilities:

**Robust timing**: The recorder's timing must be immune to wall-clock adjustments (NTP corrections, manual `date` changes, etc.). Ordinary wall-clock sources are not suitable.

**v2 timing format**: Add a `-f v1|v2` flag to sesrec (default: v2). The v2 timing file begins with the header line `# sesrec-timing v2 monotonic`, followed by data lines containing `<absolute_timestamp_seconds> <byte_count>` (absolute timestamps rather than deltas). The existing delta-based format is v1.

**Backward-compatible replay**: sesplay must support both v1 and v2 timing files, automatically determining which format is in use and replaying both correctly.

**Recording analysis**: Add `--analyze` to sesplay that prints a JSON object to stdout (no replay) with these fields:
- `format_version`: 1 or 2
- `total_chunks`: number of timing entries
- `total_bytes`: sum of all byte counts
- `total_duration_sec`: v1: sum of all delays; v2: last minus first timestamp (0.0 if ≤1 chunk)
- `mean_delay_sec`: v1: `total_duration_sec / total_chunks`; v2: `total_duration_sec / (total_chunks - 1)` when >1 chunk, else 0.0
- `max_delay_sec`: largest inter-chunk delay (0.0 if ≤1 chunk for v2)
- `min_delay_sec`: smallest inter-chunk delay (0.0 if ≤1 chunk for v2)

Build with `make` in `/app/`.
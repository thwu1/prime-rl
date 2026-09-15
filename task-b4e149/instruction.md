A session recording toolkit at `/app/` captures terminal output with timing data for replay and analysis. It consists of three C programs built with `make` in `/app/`:

- `/app/bin/evrecord` — records a command's stdout/stderr with per-chunk timing deltas
- `/app/bin/evreplay` — replays a recording, reproducing inter-event delays
- `/app/bin/evanalyze` — computes session statistics from a timing file

Users report the following fidelity issues:

- Recording the same fast command (e.g., `echo hello`) multiple times produces wildly varying first-entry delays, ranging from near-zero to almost a full second, even though the output appears instantly.
- Timing entries appear shifted by one position: each delay value seems to describe the wait time for the *previous* chunk rather than the one it's paired with.
- The analyzer's "Analyzed entries" count is always one fewer than "Total entries", and its total-time calculation excludes the first entry's delay.
- Despite these recording inaccuracies, the replayer produces roughly correct visual output, suggesting compensating workarounds may exist in other programs.

**Part 1 — Diagnose and fix all timing bugs.** Investigate the source code in `/app/src/`, identify every root cause, and apply coordinated fixes across all three programs. Remove any compensating workarounds that mask bugs in other components. After your fixes, recordings must have accurate per-event timing, the replayer must work without byte-count shifting, and the analyzer must count every entry.

**Part 2 — Design and implement `/app/bin/evaudit`.** Create a new validation tool (source at `/app/src/evaudit.c`) that audits a recording's correctness. It takes a timing file and data file as arguments:

    evaudit <timing_file> <data_file>

evaudit must perform these checks and report results in this exact format:

    === Recording Audit ===
    Timing entries: <N>
    Total bytes (timing): <N>
    Total bytes (data): <N>
    Byte match: <yes|no>
    First delay: <N.NNNNNNs> [<ok|anomalous>]
    Negative delays: <N>
    Verdict: <PASS|FAIL>

Rules:
- "First delay" is anomalous if >= 0.5 seconds
- "Byte match" compares the sum of byte counts in the timing file against the size of the raw recorded content in the data file (excluding metadata header/footer lines — see the data file conventions in `/app/src/common.h` and how the recorder writes session markers)
- "Verdict" is PASS only when: entries > 0, byte match is yes, first delay is ok, and negative delays is 0
- Exit code: 0 for PASS, 1 for FAIL
- Add the build target to `/app/Makefile` so `make` builds all four programs
- Include `/app/src/common.h`
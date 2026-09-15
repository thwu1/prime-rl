The `/app/` directory contains a session recording/replay system. `recorder.c` captures subprocess stdout/stderr into a data file (raw bytes) and a timing file (one entry per output chunk: delay in seconds followed by byte count). `replayer.c` reads these files to reproduce the recorded output with timing. Both are built via `/app/Makefile`.

Users report that recordings are unreliable. When recording subprocesses with known, deterministic timing patterns (e.g., output chunks separated by precise `sleep()` calls), the timing entries in the resulting timing file do not accurately reflect the actual inter-chunk delays. Furthermore, despite these timing inaccuracies in the recorder, the replayer still manages to produce output in roughly the right order — which should not be possible with corrupted timing data unless the replayer is somehow compensating.

Your deliverables:

- **Corrected `/app/recorder.c` and `/app/replayer.c`** — Recordings must faithfully capture real inter-chunk timing with sub-second precision on the first entry. Playback must reproduce output correctly using straightforward delay-then-emit semantics.

- **`/app/ANALYSIS.md`** — Root-cause analysis of every defect you find in the recording pipeline, how defects in the two programs interact with each other, and the design rationale for your migration tool (below). Must demonstrate deep understanding of the timing architecture, not surface-level observations.

- **`/app/migrator.c`** — Converts legacy recordings (made by the original buggy recorder) into correctly-timed recordings usable by your fixed replayer. CLI: `-d`/`-t` for input data/timing files, `-D`/`-T` for output data/timing files. Must handle comment lines (starting with `#`) in timing files. Data file is copied unchanged.

- **`/app/validator.c`** — Recording integrity checker. CLI: `-d`/`-t` flags. Checks that the sum of byte counts across all timing entries equals the data file size and that no entry has a negative delay. Skips comment lines. Exits 0 silently if valid, exits 1 with diagnostics on stderr if invalid.

- **Updated `/app/Makefile`** — Builds all four tools. Rebuild everything after your changes.
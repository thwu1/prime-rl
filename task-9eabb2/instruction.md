The C library at `/app/src/mfp.c` implements a binary format parser with four known vulnerabilities described in `/app/docs/bugs.md`. Your task is to create MAGMA-compatible ground-truth instrumentation patches for each bug.

Produce four unified diff patch files at `/app/patches/MFP001.patch` through `/app/patches/MFP004.patch`. Each patch must conform to the MAGMA instrumentation framework as documented in the environment. Study the following reference materials to understand the required format and conventions:

- `/app/docs/patch_format.md` — patch format specification with examples from real CVE patches
- `/app/docs/bugs.md` — vulnerability descriptions for MFP001–MFP004
- `/app/src/canary.h` — canary framework definitions and API
- `/app/corpus/` — crash-triggering test inputs (one per bug)
- `/app/scripts/apply_patches.sh` — patch application script
- `/app/scripts/build.sh` — build script (modes: `canary`, `fixed`, `default`)
- `/app/src_backup/` — clean source copy for rebuilding after failed patch attempts

Acceptance criteria:

1. All four patches apply cleanly via `bash /app/scripts/apply_patches.sh`
2. The patched source compiles successfully in both canary and fixed build modes
3. In canary mode, processing each bug's crash input from `/app/corpus/` produces a triggered count greater than zero for that bug
4. In fixed mode, no crash input causes a signal death
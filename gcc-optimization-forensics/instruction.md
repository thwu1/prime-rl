Five C programs are located in `/app/cases/` (case1.c through case5.c). Some of these programs contain latent defects that cause their compiled behavior to diverge depending on GCC's optimization level, while others are entirely sound.

Produce the following:

**`/app/report.json`** — A forensic report evaluating each program:

```json
{
  "caseN": {
    "output_O0": "<exact stdout when compiled with -O0>",
    "output_O2": "<exact stdout when compiled with -O2>",
    "behavior_differs": true|false,
    "ub_type": "<diagnosis of the defect that enables the divergence, or 'none'>",
    "flag": "<GCC flag (without leading dash) whose adjustment resolves the divergence, or empty string>",
    "correct_output": "<the output that matches the programmer's intended semantics>"
  }
}
```

**`/app/fixed/caseN.c`** — For each defective program, a corrected version that preserves the original algorithm's purpose while producing identical, correct output at both `-O0` and `-O2`. No fixed version is needed for sound programs.
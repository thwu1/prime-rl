Build a Python command-line tool at `/app/refcond.py` that computes and analyzes general-position systematic absences for all 230 crystallographic space groups (ITC standard settings).

**Commands:**

1. `python3 /app/refcond.py check <SG> <h> <k> <l>`
   Print `absent` or `allowed` on stdout.

2. `python3 /app/refcond.py batch-check <SG>`
   Read `h k l` triples (whitespace-separated, one per line) from stdin. Print a JSON array: `[{"h":int,"k":int,"l":int,"status":"absent"|"allowed"}, ...]`.

3. `python3 /app/refcond.py identify <CRYSTAL_SYSTEM>`
   Read `h k l absent|observed` lines from stdin. Print `{"compatible_space_groups":[...]}` listing every space group number within the crystal system whose general-position reflection conditions are consistent with all observations. Crystal systems: `triclinic`, `monoclinic`, `orthorhombic`, `tetragonal`, `trigonal`, `hexagonal`, `cubic`.

4. `python3 /app/refcond.py derive <SG>`
   Algorithmically determine and output the symbolic reflection conditions as JSON: `{"conditions":[{"reflection_type":"<subset>","condition":"<rule>"}, ...]}`. Standard subsets to report: `hkl`, `0kl`, `h0l`, `hk0`, `hhl`, `h00`, `0k0`, `00l`. Rules use ITC Vol. A notation (e.g. `h+k+l=2n`, `l=2n`, `k=2n,l=2n`, `2h+l=4n`, `-h+k+l=3n`). Only include subsets where systematic absences exist. Multiple constraints on the same subset are comma-joined in a single condition string.

5. `python3 /app/refcond.py check-transformed <SG> '<P_json>'`
   `P_json` is a row-major 3x3 integer matrix encoding the direct-space basis change `(a',b',c') = (a,b,c)P`. Read `h' k' l'` triples from stdin (in the transformed basis). Print `absent` or `allowed` per line. Transformed indices that do not map to integer Miller indices in the standard setting are absent.

**Requirements:**

- All 230 space groups, numbers 1-230, ITC standard settings.
- R-centered groups use hexagonal axes (obverse setting).
- Handle negative and zero Miller indices correctly. The null reflection (0,0,0) is absent.
- Exit code 0 on success; nonzero on invalid input.

**Verification:** `bash /tests/test.sh`

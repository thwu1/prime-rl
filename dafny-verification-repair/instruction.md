Three Dafny programs in `/app/` have been stripped of their verification annotations (loop invariants, assertions, decreases clauses): `sel_sort.dfy` (selection sort), `insertion_sort.dfy` (insertion sort), and `seq_max_sum.dfy` (maximum contiguous subsequence sum with two algorithm variants).

Modify each program so that `dafny verify /app/<file>.dfy` succeeds with 0 errors for all three files. Constraints:

- Preserve all original `requires` and `ensures` clauses exactly as written.
- Do not use `assume false` or `{:verify false}`.
- You may add `invariant`, `decreases`, `assert`, ghost variables, and lemma calls, but do not change the executable code logic.

Dafny 4.4.0 is installed and available on PATH. Original unmodified copies are at `/app/.originals/` for reference.
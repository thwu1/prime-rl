A processor's floating-point division unit shipped with a defective quotient-selection lookup table, producing incorrect results for certain inputs. You have data extracted from silicon of both the defective and corrected chip revisions:

- `/app/buggy_rom.bin` — Binary ROM dump from the defective chip.
- `/app/fixed_rom.pla` — PLA (Programmable Logic Array) specification from the corrected revision.
- `/app/test_vectors.csv` — Reference division results for validation.
- `/app/context.md` — Data format documentation and division algorithm context.

## Deliverables

### `/app/tables.db` — SQLite database

An SQLite3 database containing three tables:

- `buggy(d_idx INTEGER, p_idx INTEGER, q INTEGER, PRIMARY KEY(d_idx, p_idx))` — all 2048 entries reconstructed from the defective ROM dump
- `fixed(d_idx INTEGER, p_idx INTEGER, q INTEGER, PRIMARY KEY(d_idx, p_idx))` — all 2048 entries reconstructed from the corrected PLA specification
- `diffs(d_idx INTEGER, p_idx INTEGER, buggy_q INTEGER, fixed_q INTEGER, PRIMARY KEY(d_idx, p_idx))` — every entry where the two tables disagree

### `/app/table_map.png` — Visualization

A gnuplot-generated PNG image (minimum 800×600 pixels) visualizing the corrected lookup table's quotient-digit values across the `(d_idx, p_idx)` index space, with entries that differ from the defective table visually distinguished.

### `/app/divunit.py` — Python analysis module

Exposes these callables:

- `load_buggy_table()` → dict mapping `(d_idx, p_idx)` to quotient digit `q`
- `load_fixed_table()` → dict mapping `(d_idx, p_idx)` to quotient digit `q`
- `find_differences(table_a, table_b)` → sorted list of `(d_idx, p_idx)` tuples where values differ
- `divide(a_sig, d_sig, table, num_steps=34)` → float quotient from dividing significand `a_sig` by `d_sig` (both in `[1.0, 2.0)`), using the provided lookup table

### `/app/results.json` — Analysis results

JSON containing:

- `"num_differences"` — integer count of disagreeing entries
- `"differences"` — list of `[d_idx, p_idx, buggy_q, correct_q]` for each disagreeing entry, sorted by `(d_idx, p_idx)`
- `"bug_pattern"` — string describing the systematic nature of the defect and why it corrupts division results
- `"bug_demonstrations"` — list of at least 3 dicts, each: `{"d_idx", "p_idx", "d_val", "p_val", "buggy_q", "correct_q", "buggy_next_w", "correct_next_w"}`
- `"division_validation"` — list of at least 5 dicts `{"a", "d", "quotient"}` showing correct division results matching `a/d`
- `"table_stats"` — `{"total", "q_plus2", "q_plus1", "q_zero", "q_minus1", "q_minus2"}` for the corrected table
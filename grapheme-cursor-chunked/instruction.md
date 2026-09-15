The Python Unicode grapheme cluster segmenter at `/app/segmenter/` is broken. It fails all conformance tests against the official Unicode 17.0 test suite. There are multiple issues to resolve: the Unicode property tables have data and logic gaps, and the core segmentation functions are unimplemented.

## Project structure

- `/app/segmenter/tables.py` -- Unicode property lookup module (has issues; loads data at runtime from `/app/data/`)
- `/app/segmenter/grapheme.py` -- Segmentation module with `check_pair()` boundary classifier and stubs for `grapheme_clusters()` and `GraphemeCursor`
- `/app/data/` -- Unicode 17.0 data files (some may be missing)
- `/app/scripts/validate_tables.py` -- Diagnostic script for checking property table correctness
- `/app/Makefile` -- Build, download, and test orchestration

## Expected outcome

All tests must pass. The tests verify:
- Conformance with the official Unicode 17.0 `GraphemeBreakTest.txt` test vectors (700+ cases)
- Chunked cursor equivalence: `GraphemeCursor` must produce identical segmentation regardless of how the input text is split across chunks
- Bidirectional cursor iteration consistency via `prev_boundary`
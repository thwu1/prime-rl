Build a Unicode text segmentation system at `/app/` that correctly identifies **grapheme cluster**, **word**, and **sentence** boundaries conforming to UAX #29 (Unicode 17.0).

The delivered system must satisfy all of the following:

- `/app/libpropdb.so` exists and is a compiled C shared library that dynamically links against `libicuuc` (ICU4C).
- `/app/Makefile` exists and builds `libpropdb.so`.
- `/app/segmenter.py` is a Python module that loads and uses the C library, exposing three functions:
  - `grapheme_boundaries(codepoints: list[int]) -> list[int]`
  - `word_boundaries(codepoints: list[int]) -> list[int]`
  - `sentence_boundaries(codepoints: list[int]) -> list[int]`

  Each function accepts a list of Unicode code point integers and returns a sorted list of boundary positions (including position 0 and `len(codepoints)`).

All 3222 official Unicode 17.0 conformance test cases must pass with zero failures:

- `/app/testdata/GraphemeBreakTest.txt` (766 cases)
- `/app/testdata/WordBreakTest.txt` (1944 cases)
- `/app/testdata/SentenceBreakTest.txt` (512 cases)

Unicode property data files are provided at `/app/testdata/`. Additional Unicode data files may be obtained from unicode.org; internet access is available.

Existing segmentation or break-iteration libraries (ICU break iterators, `uniseg`, `grapheme`, etc.) must not be used for boundary detection.
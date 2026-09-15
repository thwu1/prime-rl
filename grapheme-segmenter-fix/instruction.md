The Unicode text segmentation system at `/app/` has working grapheme cluster and word boundary segmenters. A sentence boundary segmenter is needed but not yet implemented.

The file `/app/sentence_segment.py` provides the property lookup infrastructure — it loads `libsentbreak.so` via ctypes and exposes `sentence_break_property(ch)` which returns the Sentence_Break property (ATerm, STerm, Close, Sp, Lower, Upper, OLetter, Numeric, SContinue, Sep, CR, LF, Extend, Format, Other) for any Unicode character. However, the `segment_sentences()` function is unimplemented.

Design and implement the complete UAX#29 default sentence boundary algorithm so that it passes all official Unicode 16.0 conformance test vectors at `/app/data/SentenceBreakTest.txt`. The algorithm must correctly handle:

- The SB5 meta-rule (Extend/Format character transparency)
- Context-dependent rules SB7 (abbreviation uppercase), SB8 (forward scan for lowercase), SB8a (sentence continuation), SB9–SB11 (sentence terminator sequences)
- Paragraph separator handling (SB3, SB4)

The existing grapheme segmenter (`/app/grapheme_segment.py`) and word segmenter (`/app/word_segment.py`) demonstrate the project's design patterns. The specification is at https://www.unicode.org/reports/tr29/#Sentence_Boundaries.

Run `python3 /app/validate.py` to check conformance progress. Only modify files under `/app/`.
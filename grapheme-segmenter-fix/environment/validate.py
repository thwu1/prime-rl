#!/usr/bin/env python3
"""
Unicode 16.0 Conformance Validation Suite

Validates grapheme cluster, word boundary, and sentence boundary
segmentation against the official Unicode test vectors.

Usage: python3 validate.py [--verbose]

"""

import sys
import os

sys.path.insert(0, '/app')


def parse_test_file(filepath):
    """Parse Unicode break test file (÷/× marker format with hex codepoints)."""
    tests = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for lineno, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if '#' in line:
                line = line[:line.index('#')].strip()
            if not line:
                continue

            tokens = line.split()
            codepoints = []
            markers = []
            skip = False

            for tok in tokens:
                if tok == '\u00f7':
                    markers.append(True)
                elif tok == '\u00d7':
                    markers.append(False)
                else:
                    cp = int(tok, 16)
                    if 0xD800 <= cp <= 0xDFFF:
                        skip = True
                        break
                    codepoints.append(cp)

            if skip or not codepoints:
                continue

            text = ''.join(chr(cp) for cp in codepoints)
            segments = []
            current = chr(codepoints[0])
            for i in range(1, len(codepoints)):
                if markers[i]:
                    segments.append(current)
                    current = chr(codepoints[i])
                else:
                    current += chr(codepoints[i])
            segments.append(current)
            tests.append((text, segments, lineno))

    return tests


def fmt(s):
    """Format a string as hex codepoints."""
    return ' '.join(f'U+{ord(c):04X}' for c in s)


def run_validation(name, segment_fn, test_file, verbose=False):
    """Run conformance tests and report results."""
    tests = parse_test_file(test_file)
    passed = 0
    failed = 0
    failures = []

    for text, expected, lineno in tests:
        try:
            result = segment_fn(text)
        except Exception as e:
            failed += 1
            failures.append((lineno, text, expected, None, str(e)))
            continue

        if result == expected:
            passed += 1
        else:
            failed += 1
            failures.append((lineno, text, expected, result, None))

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"{name}: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}")

    if failures:
        show = failures if verbose else failures[:20]
        for lineno, text, expected, result, error in show:
            print(f"  FAIL line {lineno}: {fmt(text)}")
            if error:
                print(f"    ERROR: {error}")
            else:
                exp_str = ' | '.join(fmt(s) for s in expected)
                got_str = ' | '.join(fmt(s) for s in result)
                print(f"    expected: [{exp_str}]")
                print(f"    got:      [{got_str}]")
        if not verbose and len(failures) > 20:
            print(f"  ... {len(failures) - 20} more (use --verbose)")

    return failed == 0


def main():
    verbose = '--verbose' in sys.argv
    all_pass = True

    try:
        from grapheme_segment import segment_graphemes
        ok = run_validation("Grapheme Cluster", segment_graphemes,
                            '/app/data/GraphemeBreakTest.txt', verbose)
        if not ok:
            all_pass = False
    except Exception as e:
        print(f"ERROR loading grapheme segmenter: {e}")
        all_pass = False

    try:
        from word_segment import segment_words
        ok = run_validation("Word Boundary", segment_words,
                            '/app/data/WordBreakTest.txt', verbose)
        if not ok:
            all_pass = False
    except Exception as e:
        print(f"ERROR loading word segmenter: {e}")
        all_pass = False

    try:
        from sentence_segment import segment_sentences
        ok = run_validation("Sentence Boundary", segment_sentences,
                            '/app/data/SentenceBreakTest.txt', verbose)
        if not ok:
            all_pass = False
    except Exception as e:
        print(f"ERROR loading sentence segmenter: {e}")
        all_pass = False

    print()
    if all_pass:
        print("All conformance tests PASSED.")
    else:
        print("FAILED \u2014 fix the segmenters and re-run.")

    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())

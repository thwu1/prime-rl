#!/usr/bin/env python3

"""
Analyzes and fixes all 8 bugs in the geodetic datum transformation engine.

Bug analysis based on the GTX binary format specification, Lagrange interpolation
theory, coordinate convention standards, and NADCON5 datum transformation conventions:

1. GridParser: Header reads deltaLon before deltaLat, but the GTX spec defines
   the order as latMin, lonMin, deltaLat, deltaLon. Fix: swap the two reads.

2. GridParser: Grid data values are read with readDouble() (8 bytes), but the
   GTX binary format stores them as single-precision floats (4 bytes).
   Fix: use readFloat().

3. BlockExtractor: Uses Math.round() to compute the base row/col for the 3x3
   block. This is wrong because the block should start one row below the cell
   containing the point, i.e., floor(fracRow)-1. Math.round gives wrong results
   when the fractional part exceeds 0.5, causing out-of-bounds crashes near
   grid boundaries. Fix: use Math.floor().

4. BiquadraticInterpolator: The Lagrange basis functions L0 and L2 are swapped.
   L0(t) should be (t-1)(t-2)/2 (equals 1 at t=0), but the code has t(t-1)/2
   (which equals 1 at t=2, i.e., L2). Fix: swap the return values.

5. DatumChainTransformer: Backward transformation adds the shift instead of
   subtracting it. For backward transforms (newer->older datum), the shift must
   be subtracted. Fix: change += to -=.

6. DatumChainTransformer: Error accumulation uses simple addition instead of
   sum-of-squares. The RSS convention requires squaring each error before
   summing, then taking sqrt at the end. Fix: accumulate err*err.

7. GridFile: getValue() inverts the row index using (nRows-1-row), which flips
   the grid north-south. The GTX format stores data starting from the
   southernmost row (latMin), so row 0 = latMin. The inversion reads the
   northernmost row as row 0. Fix: use row*nCols+col directly.

8. RegionConfig: findRegion() applies wrong longitude normalization. It converts
   positive-East longitudes (>180) to negative-West, but the method receives
   positive-East longitudes from TransformEngine and needs to compare against
   positive-East bounds in the config. The normalization should convert
   negative-West (<0) to positive-East, not the reverse.
"""

import sys

SRC = '/app/src/gov/noaa/ngs/transform'


def fix_file(path, replacements):
    """Apply a list of (old, new) string replacements to a file."""
    with open(path, 'r') as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            print(f"WARNING: Pattern not found in {path}:\n  {repr(old[:80])}", file=sys.stderr)
            continue
        content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)


# ---- Fix 7: GridFile.java ----
fix_file(f'{SRC}/GridFile.java', [
    ('return data[(nRows - 1 - row) * nCols + col];',
     'return data[row * nCols + col];'),
])
print("Fixed GridFile.java: removed row index inversion")


# ---- Fix 8: RegionConfig.java ----
fix_file(f'{SRC}/RegionConfig.java', [
    ('double eLon = lon > 180 ? lon - 360.0 : lon;',
     'double eLon = lon < 0 ? lon + 360.0 : lon;'),
])
print("Fixed RegionConfig.java: corrected longitude normalization direction")


# ---- Fix 1 & 2: GridParser.java ----
fix_file(f'{SRC}/GridParser.java', [
    # Fix 1: Swap deltaLon/deltaLat header reads
    ('grid.deltaLon = dis.readDouble();\n            grid.deltaLat = dis.readDouble();',
     'grid.deltaLat = dis.readDouble();\n            grid.deltaLon = dis.readDouble();'),
    # Fix 2: readDouble -> readFloat for grid data
    ('grid.data[i] = (float) dis.readDouble();',
     'grid.data[i] = dis.readFloat();'),
])
print("Fixed GridParser.java: header field order + data type")


# ---- Fix 3: BlockExtractor.java ----
fix_file(f'{SRC}/BlockExtractor.java', [
    ('Math.round(fracRow)', 'Math.floor(fracRow)'),
    ('Math.round(fracCol)', 'Math.floor(fracCol)'),
])
print("Fixed BlockExtractor.java: floor instead of round for block positioning")


# ---- Fix 4: BiquadraticInterpolator.java ----
# Must swap in correct order: first fix case 0, then case 2.
# After fixing case 0, the string "(t - 1) * (t - 2) / 2.0" appears in both
# case 0 and case 2. The "case N:" prefix ensures uniqueness.
with open(f'{SRC}/BiquadraticInterpolator.java', 'r') as f:
    bi = f.read()

bi = bi.replace(
    'case 0:\n                return t * (t - 1) / 2.0;',
    'case 0:\n                return (t - 1) * (t - 2) / 2.0;'
)
bi = bi.replace(
    'case 2:\n                return (t - 1) * (t - 2) / 2.0;',
    'case 2:\n                return t * (t - 1) / 2.0;'
)

with open(f'{SRC}/BiquadraticInterpolator.java', 'w') as f:
    f.write(bi)
print("Fixed BiquadraticInterpolator.java: correct Lagrange basis functions")


# ---- Fix 5 & 6: DatumChainTransformer.java ----
with open(f'{SRC}/DatumChainTransformer.java', 'r') as f:
    dc = f.read()

# Fix 5: Backward transformation sign (use surrounding comment as context)
dc = dc.replace(
    '// Apply inverse shift for backward transformation\n'
    '        result.lat += latShift / 3600.0;\n'
    '        result.lon += lonShift / 3600.0;',
    '// Apply inverse shift for backward transformation\n'
    '        result.lat -= latShift / 3600.0;\n'
    '        result.lon -= lonShift / 3600.0;'
)

# Fix 6: Error accumulation - square before summing
# This pattern appears in both forward and backward methods
dc = dc.replace(
    'result.sigLat += latErr;\n        result.sigLon += lonErr;',
    'result.sigLat += latErr * latErr;\n        result.sigLon += lonErr * lonErr;'
)

with open(f'{SRC}/DatumChainTransformer.java', 'w') as f:
    f.write(dc)
print("Fixed DatumChainTransformer.java: backward sign + RSS error accumulation")

print("\nAll 8 bugs fixed across 5 source files.")

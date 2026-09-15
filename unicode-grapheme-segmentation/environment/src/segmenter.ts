
import {
  loadAllProperties,
  getGBProperty,
  isExtendedPictographic,
  getInCBValue,
  GBProperty,
  InCBValue,
} from './properties';

const DATA_DIR = process.env.UNICODE_DATA_DIR || '/app/data';

/**
 * Convert a string to an array of code points.
 */
export function toCodePoints(text: string): number[] {
  const cps: number[] = [];
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    cps.push(code);
  }
  return cps;
}

/**
 * Convert an array of code points back to a string.
 */
export function fromCodePoints(cps: number[]): string {
  return String.fromCodePoint(...cps);
}

/**
 * Determine grapheme cluster break boundaries in a sequence of code points.
 * Returns an array of boundary positions (indices into the code point array
 * where breaks occur). A break at position i means there is a boundary
 * between cps[i-1] and cps[i]. Position 0 and cps.length are always boundaries.
 *
 * Implements UAX #29 Extended Grapheme Cluster Boundary Rules (GB1-GB999).
 */
export function graphemeBoundaries(cps: number[]): number[] {
  loadAllProperties(DATA_DIR);

  if (cps.length === 0) return [0];

  const boundaries: number[] = [0]; // GB1: sot div Any

  // Precompute properties for all code points
  const props: GBProperty[] = cps.map(cp => getGBProperty(cp));
  const extPict: boolean[] = cps.map(cp => isExtendedPictographic(cp));
  const incb: InCBValue[] = cps.map(cp => getInCBValue(cp));

  for (let i = 1; i < cps.length; i++) {
    const prev = props[i - 1];
    const curr = props[i];

    // GB3: CR x LF
    if (prev === 'CR' && curr === 'LF') {
      continue; // no break
    }

    // GB4: (Control | CR | LF) div
    if (prev === 'Control' || prev === 'CR' || prev === 'LF') {
      boundaries.push(i);
      continue;
    }

    // GB5: div (Control | CR | LF)
    if (curr === 'Control' || curr === 'CR' || curr === 'LF') {
      boundaries.push(i);
      continue;
    }

    // GB6: L x (L | V | LV | LVT)
    if (prev === 'L' && (curr === 'L' || curr === 'V' || curr === 'LV' || curr === 'LVT')) {
      continue;
    }

    // GB7: (LV | V) x (V | T)
    if ((prev === 'LV' || prev === 'V') && (curr === 'V' || curr === 'T')) {
      continue;
    }

    // GB8: (LVT | T) x T
    if ((prev === 'LVT' || prev === 'T') && curr === 'T') {
      continue;
    }

    // GB9: x (Extend | ZWJ)
    if (curr === 'Extend' || curr === 'ZWJ') {
      continue;
    }

    // GB9a: x SpacingMark
    if (curr === 'SpacingMark') {
      continue;
    }

    // GB9b: Prepend x
    if (prev === 'Prepend') {
      continue;
    }

    // GB9c: \p{InCB=Consonant} [\p{InCB=Extend}\p{InCB=Linker}]* \p{InCB=Linker}
    //       [\p{InCB=Extend}\p{InCB=Linker}]* x \p{InCB=Consonant}
    // TODO: Implement GB9c

    // GB11: \p{Extended_Pictographic} Extend* ZWJ x \p{Extended_Pictographic}
    // TODO: Implement GB11

    // GB12/GB13: Regional Indicator pairing
    if (prev === 'Regional_Indicator' && curr === 'Regional_Indicator') {
      continue;
    }

    // GB999: Any div Any
    boundaries.push(i);
  }

  boundaries.push(cps.length); // GB2: Any div eot
  return boundaries;
}

/**
 * Segment a string into extended grapheme clusters.
 */
export function segmentGraphemes(text: string): string[] {
  const cps = toCodePoints(text);
  const bounds = graphemeBoundaries(cps);
  const clusters: string[] = [];
  for (let i = 0; i < bounds.length - 1; i++) {
    const slice = cps.slice(bounds[i], bounds[i + 1]);
    clusters.push(fromCodePoints(slice));
  }
  return clusters;
}

/**
 * Parse GraphemeBreakTest.txt and run all test vectors.
 * Returns { passed, failed, total, failures }.
 */
export function runGraphemeBreakTests(testFilePath: string): {
  passed: number;
  failed: number;
  total: number;
  failures: { line: number; input: string; expected: number[]; got: number[] }[];
} {
  loadAllProperties(DATA_DIR);

  const { readFileSync } = require('fs');
  const content = readFileSync(testFilePath, 'utf-8');
  const lines = content.split('\n');

  let passed = 0;
  let failed = 0;
  const failures: { line: number; input: string; expected: number[]; got: number[] }[] = [];

  for (let lineNum = 0; lineNum < lines.length; lineNum++) {
    const line = lines[lineNum].trim();
    if (!line || line.startsWith('#')) continue;

    // Parse test line: "div XXXX x YYYY div ZZZZ div"
    // The comment part starts after a tab followed by #
    const dataStr = line.split('\t')[0].trim();
    if (!dataStr.startsWith('\u00F7')) continue;

    // Extract code points and expected boundaries
    const tokens = dataStr.split(/\s+/);
    const cps: number[] = [];
    const expectedBoundaries: number[] = [0];
    let cpIndex = 0;

    for (const token of tokens) {
      if (token === '\u00F7') {
        if (cpIndex > 0) {
          expectedBoundaries.push(cpIndex);
        }
      } else if (token === '\u00D7') {
        // no boundary
      } else {
        // hex code point
        const cp = parseInt(token, 16);
        if (!isNaN(cp)) {
          cps.push(cp);
          cpIndex++;
        }
      }
    }

    if (cps.length === 0) continue;

    const gotBoundaries = graphemeBoundaries(cps);

    const expectedStr = JSON.stringify(expectedBoundaries);
    const gotStr = JSON.stringify(gotBoundaries);

    if (expectedStr === gotStr) {
      passed++;
    } else {
      failed++;
      if (failures.length < 50) {
        failures.push({
          line: lineNum + 1,
          input: dataStr,
          expected: expectedBoundaries,
          got: gotBoundaries,
        });
      }
    }
  }

  return { passed, failed, total: passed + failed, failures };
}

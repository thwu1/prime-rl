
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
 * Uses codePointAt to correctly handle supplementary plane characters.
 */
export function toCodePoints(text: string): number[] {
  const cps: number[] = [];
  for (let i = 0; i < text.length; i++) {
    const cp = text.codePointAt(i)!;
    cps.push(cp);
    if (cp > 0xFFFF) {
      i++; // skip the low surrogate
    }
  }
  return cps;
}

export function fromCodePoints(cps: number[]): string {
  return String.fromCodePoint(...cps);
}

/**
 * Check if GB9c applies at position i.
 * GB9c: \p{InCB=Consonant} [\p{InCB=Extend}\p{InCB=Linker}]* \p{InCB=Linker}
 *       [\p{InCB=Extend}\p{InCB=Linker}]* x \p{InCB=Consonant}
 */
function checkGB9c(incb: InCBValue[], i: number): boolean {
  if (incb[i] !== 'Consonant') return false;

  // Scan backwards through optional [Extend|Linker]*
  let j = i - 1;
  while (j >= 0 && (incb[j] === 'Extend' || incb[j] === 'Linker')) {
    j--;
  }

  // Position j should be at something that stopped the scan.
  // But we need a Linker between the previous Consonant and position i.
  // The pattern is: Consonant [Extend|Linker]* Linker [Extend|Linker]* x Consonant
  // So we need to check that there is a Consonant before the [Extend|Linker]* sequence,
  // and at least one Linker in the sequence.

  // After scanning back through [Extend|Linker]*, j points to the character
  // before the sequence. It should be a Consonant.
  if (j < 0 || incb[j] !== 'Consonant') return false;

  // Check that there's at least one Linker between j+1 and i-1
  let hasLinker = false;
  for (let k = j + 1; k < i; k++) {
    if (incb[k] === 'Linker') {
      hasLinker = true;
      break;
    }
  }

  return hasLinker;
}

export function graphemeBoundaries(cps: number[]): number[] {
  loadAllProperties(DATA_DIR);

  if (cps.length === 0) return [0];

  const boundaries: number[] = [0]; // GB1

  const props: GBProperty[] = cps.map(cp => getGBProperty(cp));
  const extPict: boolean[] = cps.map(cp => isExtendedPictographic(cp));
  const incb: InCBValue[] = cps.map(cp => getInCBValue(cp));

  for (let i = 1; i < cps.length; i++) {
    const prev = props[i - 1];
    const curr = props[i];

    // GB3: CR x LF
    if (prev === 'CR' && curr === 'LF') {
      continue;
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

    // GB9c: Indic conjunct clusters
    if (checkGB9c(incb, i)) {
      continue;
    }

    // GB11: \p{Extended_Pictographic} Extend* ZWJ x \p{Extended_Pictographic}
    if (prev === 'ZWJ' && extPict[i]) {
      let j = i - 2;
      while (j >= 0 && props[j] === 'Extend') {
        j--;
      }
      if (j >= 0 && extPict[j]) {
        continue;
      }
    }

    // GB12/GB13: Regional Indicator pairing -- count preceding RI chars
    if (prev === 'Regional_Indicator' && curr === 'Regional_Indicator') {
      let riCount = 0;
      let j = i - 1;
      while (j >= 0 && props[j] === 'Regional_Indicator') {
        riCount++;
        j--;
      }
      if (riCount % 2 === 1) {
        continue; // odd number preceding = this is the second of a pair
      }
    }

    // GB999: Any div Any
    boundaries.push(i);
  }

  boundaries.push(cps.length); // GB2
  return boundaries;
}

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

    const dataStr = line.split('\t')[0].trim();
    if (!dataStr.startsWith('\u00F7')) continue;

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

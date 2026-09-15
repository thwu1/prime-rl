
import { readFileSync } from 'fs';
import { join } from 'path';

export type GBProperty =
  | 'CR' | 'LF' | 'Control' | 'Extend' | 'ZWJ'
  | 'Regional_Indicator' | 'Prepend' | 'SpacingMark'
  | 'L' | 'V' | 'T' | 'LV' | 'LVT' | 'Other';

export type InCBValue = 'None' | 'Linker' | 'Consonant' | 'Extend';

interface CodePointRange {
  start: number;
  end: number;
  value: string;
}

const gbRanges: CodePointRange[] = [];
let extPictoRanges: CodePointRange[] = [];
const incbRanges: CodePointRange[] = [];

let loaded = false;

function parsePropertyLine(line: string): { start: number; end: number; value: string } | null {
  const commentIdx = line.indexOf('#');
  const trimmed = (commentIdx >= 0 ? line.substring(0, commentIdx) : line).trim();
  if (!trimmed) return null;

  const parts = trimmed.split(';').map(s => s.trim());
  if (parts.length < 2) return null;

  const rangePart = parts[0];
  const dotDot = rangePart.indexOf('..');
  let start: number, end: number;
  if (dotDot >= 0) {
    start = parseInt(rangePart.substring(0, dotDot), 16);
    end = parseInt(rangePart.substring(dotDot + 2), 16);
  } else {
    start = parseInt(rangePart, 16);
    end = start;
  }

  if (isNaN(start) || isNaN(end)) return null;

  // Use the last field as the value to handle both 2-field and 3-field formats
  const value = parts[parts.length - 1];
  return { start, end, value };
}

function loadGBProperties(dataDir: string): void {
  const filePath = join(dataDir, 'GraphemeBreakProperty.txt');
  const content = readFileSync(filePath, 'utf-8');
  for (const line of content.split('\n')) {
    const parsed = parsePropertyLine(line);
    if (parsed) {
      gbRanges.push(parsed);
    }
  }
  gbRanges.sort((a, b) => a.start - b.start);
}

function loadExtendedPictographic(dataDir: string): void {
  try {
    const filePath = join(dataDir, 'ExtPict.txt');
    const content = readFileSync(filePath, 'utf-8');
    const ranges: CodePointRange[] = [];
    for (const line of content.split('\n')) {
      const parsed = parsePropertyLine(line);
      if (parsed) {
        ranges.push({ start: parsed.start, end: parsed.end, value: 'Extended_Pictographic' });
      }
    }
    ranges.sort((a, b) => a.start - b.start);
    extPictoRanges = ranges;
  } catch (e) {
    extPictoRanges = [];
  }
}

function loadInCB(dataDir: string): void {
  try {
    const filePath = join(dataDir, 'InCB.txt');
    const content = readFileSync(filePath, 'utf-8');
    for (const line of content.split('\n')) {
      const parsed = parsePropertyLine(line);
      if (parsed) {
        incbRanges.push(parsed);
      }
    }
    incbRanges.sort((a, b) => a.start - b.start);
  } catch (e) {
    // InCB data unavailable
  }
}

export function loadAllProperties(dataDir: string): void {
  if (loaded) return;
  loadGBProperties(dataDir);
  loadExtendedPictographic(dataDir);
  loadInCB(dataDir);
  loaded = true;
}

function findInRanges(ranges: CodePointRange[], cp: number): CodePointRange | null {
  let lo = 0, hi = ranges.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (cp < ranges[mid].start) {
      hi = mid - 1;
    } else if (cp > ranges[mid].end) {
      lo = mid + 1;
    } else {
      return ranges[mid];
    }
  }
  return null;
}

export function getGBProperty(cp: number): GBProperty {
  const range = findInRanges(gbRanges, cp);
  if (!range) return 'Other';

  switch (range.value) {
    case 'CR': return 'CR';
    case 'LF': return 'LF';
    case 'Control': return 'Control';
    case 'Extend': return 'Extend';
    case 'ZWJ': return 'ZWJ';
    case 'Regional_Indicator': return 'Regional_Indicator';
    case 'Prepend': return 'Prepend';
    case 'SpacingMark': return 'SpacingMark';
    case 'L': return 'L';
    case 'V': return 'V';
    case 'T': return 'T';
    case 'LV': return 'LV';
    case 'LVT': return 'LVT';
    default: return 'Other';
  }
}

export function isExtendedPictographic(cp: number): boolean {
  return findInRanges(extPictoRanges, cp) !== null;
}

export function getInCBValue(cp: number): InCBValue {
  const range = findInRanges(incbRanges, cp);
  if (!range) return 'None';

  switch (range.value) {
    case 'Linker': return 'Linker';
    case 'Consonant': return 'Consonant';
    case 'Extend': return 'Extend';
    default: return 'None';
  }
}

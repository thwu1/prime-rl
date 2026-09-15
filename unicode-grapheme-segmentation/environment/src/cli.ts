#!/usr/bin/env node

import { segmentGraphemes, fromCodePoints, runGraphemeBreakTests } from './segmenter';
import { join } from 'path';

const DATA_DIR = process.env.UNICODE_DATA_DIR || '/app/data';

function usage(): void {
  console.error('Usage:');
  console.error('  segmenter graphemes <text>       Segment text into grapheme clusters');
  console.error('  segmenter graphemes-hex <hex>... Segment hex code points into clusters');
  console.error('  segmenter test                   Run official GraphemeBreakTest vectors');
  console.error('  segmenter test-json              Run tests and output JSON results');
  process.exit(1);
}

const args = process.argv.slice(2);
if (args.length === 0) usage();

const command = args[0];

switch (command) {
  case 'graphemes': {
    if (args.length < 2) {
      console.error('Error: missing text argument');
      process.exit(1);
    }
    const text = args.slice(1).join(' ');
    const clusters = segmentGraphemes(text);
    for (const cluster of clusters) {
      // Output each cluster with its code points in hex
      const cps = [...cluster].map(ch => {
        const cp = ch.codePointAt(0)!;
        return cp.toString(16).toUpperCase().padStart(4, '0');
      });
      console.log(`${cluster}\t[${cps.join(' ')}]`);
    }
    break;
  }

  case 'graphemes-hex': {
    if (args.length < 2) {
      console.error('Error: missing hex code point arguments');
      process.exit(1);
    }
    const cps = args.slice(1).map(h => parseInt(h, 16));
    if (cps.some(isNaN)) {
      console.error('Error: invalid hex code point');
      process.exit(1);
    }
    const text = fromCodePoints(cps);
    const clusters = segmentGraphemes(text);
    for (const cluster of clusters) {
      const clusterCps = [...cluster].map(ch => {
        const cp = ch.codePointAt(0)!;
        return cp.toString(16).toUpperCase().padStart(4, '0');
      });
      console.log(`[${clusterCps.join(' ')}]`);
    }
    break;
  }

  case 'test': {
    const testFile = join(DATA_DIR, 'GraphemeBreakTest.txt');
    const result = runGraphemeBreakTests(testFile);
    console.log(`GraphemeBreakTest results: ${result.passed}/${result.total} passed, ${result.failed} failed`);
    if (result.failures.length > 0) {
      console.log('\nFirst failures:');
      for (const f of result.failures.slice(0, 10)) {
        console.log(`  Line ${f.line}: expected ${JSON.stringify(f.expected)}, got ${JSON.stringify(f.got)}`);
        console.log(`    Input: ${f.input}`);
      }
    }
    process.exit(result.failed > 0 ? 1 : 0);
    break;
  }

  case 'test-json': {
    const testFile = join(DATA_DIR, 'GraphemeBreakTest.txt');
    const result = runGraphemeBreakTests(testFile);
    console.log(JSON.stringify(result));
    process.exit(result.failed > 0 ? 1 : 0);
    break;
  }

  default:
    console.error(`Unknown command: ${command}`);
    usage();
}

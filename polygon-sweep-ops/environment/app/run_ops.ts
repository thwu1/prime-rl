import { readFileSync } from 'fs';
import boolean from './src/index';
import { INTERSECTION, UNION, DIFFERENCE, XOR } from './src/operation';


const input = JSON.parse(readFileSync('/dev/stdin', 'utf-8'));
const { subject, clipping, operation } = input;

const ops: Record<string, number> = {
  intersection: INTERSECTION,
  union: UNION,
  difference: DIFFERENCE,
  xor: XOR
};

if (!(operation in ops)) {
  console.error(`Unknown operation: ${operation}`);
  process.exit(1);
}

const result = boolean(subject, clipping, ops[operation]);
console.log(JSON.stringify(result));

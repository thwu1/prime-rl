import * as fs from 'fs';
import { TypedData } from './encoder';
import { computeSigningHash } from './hasher';


const input = fs.readFileSync('/dev/stdin', 'utf8');
const typedData: TypedData = JSON.parse(input);
const result = computeSigningHash(typedData);
console.log(result.signingHash);

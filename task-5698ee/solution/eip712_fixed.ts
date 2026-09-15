import * as fs from 'fs';
import { TypedData, findTypeDependencies, encodeType, typeHash } from './encoder';
import { computeSigningHash } from './hasher';


const args = process.argv.slice(2);
const input = fs.readFileSync('/dev/stdin', 'utf8');
const typedData: TypedData = JSON.parse(input);
const result = computeSigningHash(typedData);

if (args[0] === '--json') {
  const deps = findTypeDependencies(typedData.primaryType, typedData.types);
  deps.delete(typedData.primaryType);
  deps.delete('EIP712Domain');

  const referencedTypes: Record<string, { typeHash: string; encodeType: string }> = {};
  for (const dep of Array.from(deps).sort()) {
    referencedTypes[dep] = {
      typeHash: '0x' + typeHash(dep, typedData.types).toString('hex'),
      encodeType: encodeType(dep, typedData.types),
    };
  }

  const output = {
    signingHash: result.signingHash,
    domainSeparator: result.domainSeparator,
    messageHash: result.messageHash,
    primaryType: typedData.primaryType,
    encodeType: encodeType(typedData.primaryType, typedData.types),
    typeHash: '0x' + typeHash(typedData.primaryType, typedData.types).toString('hex'),
    referencedTypes,
  };

  console.log(JSON.stringify(output));
} else if (args[0] === '--verify') {
  const expectedHash = args[1];
  console.log(result.signingHash);
  process.exitCode = result.signingHash.toLowerCase() === expectedHash.toLowerCase() ? 0 : 1;
} else {
  console.log(result.signingHash);
}

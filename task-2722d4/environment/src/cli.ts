import { readFileSync } from 'fs';
import {
  computeSigningHash,
  encodeType,
  typeHash,
  hashStruct,
} from './eip712';
import type { TypedData } from './eip712';


try {
  const input = readFileSync(0, 'utf-8');
  const typedData: TypedData = JSON.parse(input);

  const result: Record<string, string | null> = {};

  try {
    result.encodeType = encodeType(typedData.primaryType, typedData.types);
  } catch {
    result.encodeType = null;
  }

  try {
    result.typeHash = typeHash(typedData.primaryType, typedData.types);
  } catch {
    result.typeHash = null;
  }

  try {
    const domainTypes = { EIP712Domain: typedData.types.EIP712Domain };
    result.domainSeparator = hashStruct(
      'EIP712Domain',
      typedData.domain,
      domainTypes,
    );
  } catch {
    result.domainSeparator = null;
  }

  try {
    if (typedData.primaryType !== 'EIP712Domain') {
      result.messageStructHash = hashStruct(
        typedData.primaryType,
        typedData.message,
        typedData.types,
      );
    }
  } catch {
    result.messageStructHash = null;
  }

  try {
    result.signingHash = computeSigningHash(typedData);
  } catch {
    result.signingHash = null;
  }

  console.log(JSON.stringify(result));
} catch (e: any) {
  console.error(`Fatal error: ${e.message}`);
  process.exit(1);
}

import { keccak256 } from 'js-sha3';
import { TypeField, TypedData, typeHash, encodeValue } from './encoder';


/**
 * Encode all data fields of a struct instance, prefixed by its typeHash.
 */
export function encodeData(
  primaryType: string,
  data: Record<string, any>,
  types: Record<string, TypeField[]>
): Buffer {
  const parts: Buffer[] = [typeHash(primaryType, types)];
  for (const field of types[primaryType]) {
    parts.push(encodeValue(field.type, data[field.name], types, hashStruct));
  }
  return Buffer.concat(parts);
}

/**
 * Compute hashStruct = keccak256(encodeData(...))
 */
export function hashStruct(
  primaryType: string,
  data: Record<string, any>,
  types: Record<string, TypeField[]>
): Buffer {
  return Buffer.from(keccak256.arrayBuffer(encodeData(primaryType, data, types)));
}

export interface SigningResult {
  signingHash: string;
  domainSeparator: string;
  messageHash: string;
}

/**
 * Compute the EIP-712 signing hash.
 */
export function computeSigningHash(typedData: TypedData): SigningResult {
  const domainSep = hashStruct('EIP712Domain', typedData.domain, typedData.types);
  const msgHash = hashStruct(typedData.primaryType, typedData.message, typedData.types);

  const toHash = Buffer.concat([
    Buffer.from([0x19, 0x01]),
    msgHash,
    domainSep,
  ]);

  return {
    signingHash: '0x' + keccak256(toHash),
    domainSeparator: '0x' + domainSep.toString('hex'),
    messageHash: '0x' + msgHash.toString('hex'),
  };
}

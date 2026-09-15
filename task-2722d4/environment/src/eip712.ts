import { keccak256 } from 'js-sha3';


export interface TypedDataField {
  name: string;
  type: string;
}

export interface TypedData {
  types: Record<string, TypedDataField[]>;
  primaryType: string;
  domain: Record<string, any>;
  message: Record<string, any>;
}

function hexToBytes(hex: string): Uint8Array {
  const h = hex.startsWith('0x') ? hex.slice(2) : hex;
  const padded = h.length % 2 === 1 ? '0' + h : h;
  const bytes = new Uint8Array(padded.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(padded.substring(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function concatBytes(...arrays: Uint8Array[]): Uint8Array {
  const total = arrays.reduce((sum, a) => sum + a.length, 0);
  const result = new Uint8Array(total);
  let offset = 0;
  for (const a of arrays) {
    result.set(a, offset);
    offset += a.length;
  }
  return result;
}

function keccak256Bytes(data: Uint8Array): Uint8Array {
  return hexToBytes(keccak256(data));
}

function bigIntToBytes32(val: bigint): Uint8Array {
  const buf = new Uint8Array(32);
  let v = val;
  for (let i = 31; i >= 0; i--) {
    buf[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  return buf;
}

/**
 * Recursively collect all struct type dependencies for a given type.
 */
function findTypeDependencies(
  primaryType: string,
  types: Record<string, TypedDataField[]>,
  results: Set<string> = new Set(),
): Set<string> {
  if (results.has(primaryType) || types[primaryType] === undefined) {
    return results;
  }
  results.add(primaryType);
  for (const field of types[primaryType]) {
    findTypeDependencies(field.type, types, results);
  }
  return results;
}

/**
 * Produce the canonical EIP-712 type encoding string.
 */
export function encodeType(
  primaryType: string,
  types: Record<string, TypedDataField[]>,
): string {
  const deps = findTypeDependencies(primaryType, types);
  deps.delete(primaryType);

  const sorted = [...Array.from(deps).sort(), primaryType];

  let result = '';
  for (const t of sorted) {
    if (!types[t]) continue;
    result += `${t}(${types[t].map((f) => `${f.type} ${f.name}`).join(',')})`;
  }
  return result;
}

/**
 * Encode a single value according to its EIP-712 type for ABI packing.
 */
function encodeValue(
  type: string,
  value: any,
  types: Record<string, TypedDataField[]>,
): Uint8Array {
  if (types[type] !== undefined) {
    return hashStructBytes(type, value, types);
  }

  if (type === 'string') {
    const strBytes = new TextEncoder().encode(value ?? '');
    const buf = new Uint8Array(32);
    const toCopy = strBytes.length > 32 ? strBytes.slice(0, 32) : strBytes;
    buf.set(toCopy);
    return buf;
  }

  if (type === 'bytes') {
    let data: Uint8Array;
    if (typeof value === 'string' && value.startsWith('0x')) {
      data = hexToBytes(value);
    } else if (typeof value === 'string') {
      data = new TextEncoder().encode(value);
    } else {
      data = new Uint8Array(value);
    }
    return keccak256Bytes(data);
  }

  if (type === 'address') {
    const addr = (value as string).toLowerCase().replace('0x', '');
    const normalized = addr.padStart(40, '0');
    return hexToBytes(normalized);
  }

  if (type === 'bool') {
    const buf = new Uint8Array(32);
    buf[31] = value ? 1 : 0;
    return buf;
  }

  if (type.startsWith('uint')) {
    const val = BigInt(value);
    return bigIntToBytes32(val);
  }

  if (type.startsWith('int') && !type.includes('[')) {
    let val = BigInt(value);
    if (val < 0n) {
      val = -val;
    }
    return bigIntToBytes32(val);
  }

  if (type.startsWith('bytes') && !type.includes('[')) {
    const size = parseInt(type.slice(5));
    let data: Uint8Array;
    if (typeof value === 'string' && value.startsWith('0x')) {
      data = hexToBytes(value);
    } else if (value instanceof Uint8Array) {
      data = value;
    } else {
      data = new Uint8Array(0);
    }
    const buf = new Uint8Array(32);
    const trimmed = data.slice(0, size);
    buf.set(trimmed, 32 - trimmed.length);
    return buf;
  }

  if (type.endsWith(']')) {
    throw new Error(`Array types are not yet implemented: ${type}`);
  }

  throw new Error(`Unsupported type: ${type}`);
}

/**
 * ABI-encode the data for a struct: typeHash ++ encoded member values.
 */
function encodeData(
  primaryType: string,
  data: Record<string, any>,
  types: Record<string, TypedDataField[]>,
): Uint8Array {
  const typeString = encodeType(primaryType, types);
  const typeHashBytes = keccak256Bytes(new TextEncoder().encode(typeString));

  const parts: Uint8Array[] = [typeHashBytes];
  for (const field of types[primaryType]) {
    parts.push(encodeValue(field.type, data[field.name], types));
  }
  return concatBytes(...parts);
}

function hashStructBytes(
  primaryType: string,
  data: Record<string, any>,
  types: Record<string, TypedDataField[]>,
): Uint8Array {
  return keccak256Bytes(encodeData(primaryType, data, types));
}

export function hashStruct(
  primaryType: string,
  data: Record<string, any>,
  types: Record<string, TypedDataField[]>,
): string {
  return '0x' + bytesToHex(hashStructBytes(primaryType, data, types));
}

export function typeHash(
  primaryType: string,
  types: Record<string, TypedDataField[]>,
): string {
  const typeString = encodeType(primaryType, types);
  return '0x' + keccak256(new TextEncoder().encode(typeString));
}

/**
 * Compute the EIP-712 signing hash for a complete TypedData payload.
 */
export function computeSigningHash(typedData: TypedData): string {
  const domainTypes: Record<string, TypedDataField[]> = {
    EIP712Domain: typedData.types.EIP712Domain,
  };

  const domainHash = hashStructBytes(
    'EIP712Domain',
    typedData.domain,
    domainTypes,
  );

  const prefix = new Uint8Array([0x19, 0x00]);

  if (typedData.primaryType === 'EIP712Domain') {
    return '0x' + bytesToHex(keccak256Bytes(concatBytes(prefix, domainHash)));
  }

  const messageHash = hashStructBytes(
    typedData.primaryType,
    typedData.message,
    typedData.types,
  );

  return (
    '0x' +
    bytesToHex(keccak256Bytes(concatBytes(prefix, domainHash, messageHash)))
  );
}

import { keccak256 } from 'js-sha3';


export interface TypeField {
  name: string;
  type: string;
}

export interface TypedData {
  types: Record<string, TypeField[]>;
  primaryType: string;
  domain: Record<string, any>;
  message: Record<string, any>;
}

/**
 * Recursively find all struct type dependencies for a given type.
 * Strips array brackets to resolve base struct types.
 */
export function findTypeDependencies(
  primaryType: string,
  types: Record<string, TypeField[]>,
  results: Set<string> = new Set()
): Set<string> {
  let baseType = primaryType;
  while (baseType.endsWith(']')) {
    baseType = baseType.slice(0, baseType.lastIndexOf('['));
  }
  if (results.has(baseType) || types[baseType] === undefined) {
    return results;
  }
  results.add(baseType);
  for (const field of types[baseType]) {
    findTypeDependencies(field.type, types, results);
  }
  return results;
}

/**
 * Encode the type string for a struct type per EIP-712.
 * Primary type first, then remaining deps sorted alphabetically.
 */
export function encodeType(
  primaryType: string,
  types: Record<string, TypeField[]>
): string {
  const deps = findTypeDependencies(primaryType, types);
  deps.delete(primaryType);
  const sorted = [primaryType, ...Array.from(deps).sort()];

  let result = '';
  for (const typeName of sorted) {
    const fields = types[typeName];
    if (!fields) {
      throw new Error(`Unknown type: ${typeName}`);
    }
    result += `${typeName}(${fields.map(f => `${f.type} ${f.name}`).join(',')})`;
  }
  return result;
}

/**
 * Compute the keccak256 type hash of an encoded type string.
 */
export function typeHash(
  primaryType: string,
  types: Record<string, TypeField[]>
): Buffer {
  const encoded = encodeType(primaryType, types);
  return Buffer.from(keccak256.arrayBuffer(Buffer.from(encoded, 'utf8')));
}

/**
 * Encode a single value according to its EIP-712 type.
 * Returns a 32-byte Buffer.
 */
export function encodeValue(
  fieldType: string,
  value: any,
  types: Record<string, TypeField[]>,
  hashStructFn: (pt: string, data: Record<string, any>, t: Record<string, TypeField[]>) => Buffer
): Buffer {
  // Custom struct type
  if (types[fieldType] !== undefined) {
    if (value == null) {
      return Buffer.alloc(32);
    }
    return hashStructFn(fieldType, value, types);
  }

  // Array type
  if (fieldType.endsWith(']')) {
    const baseType = fieldType.slice(0, fieldType.lastIndexOf('['));
    if (!Array.isArray(value)) {
      throw new Error(`Expected array for type ${fieldType}`);
    }
    const encoded = value.map((item: any) => encodeValue(baseType, item, types, hashStructFn));
    return Buffer.from(keccak256.arrayBuffer(Buffer.concat(encoded)));
  }

  // Dynamic type: string
  if (fieldType === 'string') {
    const str = value == null ? '' : String(value);
    return Buffer.from(keccak256.arrayBuffer(Buffer.from(str, 'utf8')));
  }

  // Dynamic type: bytes — decode hex-encoded strings as raw bytes
  if (fieldType === 'bytes') {
    let buf: Buffer;
    if (typeof value === 'string') {
      if (value.startsWith('0x') || value.startsWith('0X')) {
        buf = Buffer.from(value.slice(2), 'hex');
      } else {
        buf = Buffer.from(value, 'utf8');
      }
    } else if (Buffer.isBuffer(value)) {
      buf = value;
    } else {
      buf = Buffer.from(value);
    }
    return Buffer.from(keccak256.arrayBuffer(buf));
  }

  // Atomic type: bool
  if (fieldType === 'bool') {
    const b = Buffer.alloc(32);
    if (value) b[31] = 1;
    return b;
  }

  // Atomic type: address
  if (fieldType === 'address') {
    const b = Buffer.alloc(32);
    let hex: string;
    if (typeof value === 'string') {
      hex = value.startsWith('0x') ? value.slice(2) : value;
    } else {
      hex = value.toString(16);
    }
    hex = hex.toLowerCase().padStart(40, '0');
    Buffer.from(hex, 'hex').copy(b, 12, 0, 20);
    return b;
  }

  // Atomic type: uintN
  if (fieldType.startsWith('uint')) {
    const b = Buffer.alloc(32);
    let n = BigInt(value);
    for (let i = 31; i >= 0; i--) {
      b[i] = Number(n & 0xffn);
      n >>= 8n;
    }
    return b;
  }

  // Atomic type: intN (signed) — two's complement for negative values
  if (fieldType.startsWith('int')) {
    const b = Buffer.alloc(32);
    let n = BigInt(value);
    if (n < 0n) {
      n = (1n << 256n) + n;
    }
    for (let i = 31; i >= 0; i--) {
      b[i] = Number(n & 0xffn);
      n >>= 8n;
    }
    return b;
  }

  // Atomic type: bytesN (fixed-size)
  if (fieldType.startsWith('bytes')) {
    const size = parseInt(fieldType.slice(5), 10);
    if (isNaN(size) || size < 1 || size > 32) {
      throw new Error(`Invalid fixed bytes type: ${fieldType}`);
    }
    const b = Buffer.alloc(32);
    let raw: Buffer;
    if (typeof value === 'string' && value.startsWith('0x')) {
      raw = Buffer.from(value.slice(2), 'hex');
    } else if (typeof value === 'number') {
      raw = Buffer.alloc(size);
      let v = BigInt(value);
      for (let i = size - 1; i >= 0; i--) {
        raw[i] = Number(v & 0xffn);
        v >>= 8n;
      }
    } else if (typeof value === 'string') {
      raw = Buffer.from(value, 'utf8');
    } else {
      raw = Buffer.from(value);
    }
    raw.copy(b, 0, 0, Math.min(raw.length, size));
    return b;
  }

  throw new Error(`Unsupported EIP-712 type: ${fieldType}`);
}

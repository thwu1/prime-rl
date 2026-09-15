#!/usr/bin/env python3

"""
Writes the complete corrected Automerge columnar codec to /app/src/codec.ts.
Fixes 8 bugs and implements 7 stub functions.
"""

import os
import json

CODEC_PATH = '/app/src/codec.ts'
PKG_PATH = '/app/package.json'
TSC_PATH = '/app/tsconfig.json'

os.makedirs('/app/src', exist_ok=True)


FIXED_CODEC = r'''// Automerge Binary Document Format — Columnar Encoding Codec

import { createHash } from 'crypto';

// ========== LEB128 Encoding ==========

export function encodeULEB128(value: bigint): Uint8Array {
  if (value < 0n) throw new Error('Value must be non-negative for uLEB128');
  if (value === 0n) return new Uint8Array([0]);

  const bytes: number[] = [];
  let remaining = value;
  while (remaining > 0n) {
    let byte = Number(remaining & 0x7fn);
    remaining >>= 7n;
    if (remaining > 0n) byte |= 0x80;
    bytes.push(byte);
  }
  return new Uint8Array(bytes);
}

export function decodeULEB128(data: Uint8Array, offset: number = 0): [bigint, number] {
  let result = 0n;
  let shift = 0n;
  let pos = offset;
  let byteCount = 0;

  while (pos < data.length) {
    const byte = data[pos];
    result |= BigInt(byte & 0x7f) << shift;
    shift += 7n;
    pos++;
    byteCount++;

    if ((byte & 0x80) === 0) {
      if (byteCount > 1 && byte === 0) {
        throw new Error('Overlong uLEB128 encoding');
      }
      return [result, pos - offset];
    }

    if (shift > 63n) throw new Error('uLEB128 value exceeds 64 bits');
  }
  throw new Error('Unterminated uLEB128 sequence');
}

export function encodeLEB128(value: bigint): Uint8Array {
  const bytes: number[] = [];
  let more = true;
  let v = value;

  while (more) {
    let byte = Number(v & 0x7fn);
    v >>= 7n;

    if ((v === 0n && (byte & 0x40) === 0) ||
        (v === -1n && (byte & 0x40) !== 0)) {
      more = false;
    } else {
      byte |= 0x80;
    }
    bytes.push(byte);
  }
  return new Uint8Array(bytes);
}

export function decodeLEB128(data: Uint8Array, offset: number = 0): [bigint, number] {
  let result = 0n;
  let shift = 0n;
  let pos = offset;

  while (pos < data.length) {
    const byte = data[pos];
    result |= BigInt(byte & 0x7f) << shift;
    shift += 7n;
    pos++;

    if ((byte & 0x80) === 0) {
      if (shift < 64n && (byte & 0x40) !== 0) {
        result |= -(1n << shift);
      }
      return [result, pos - offset];
    }

    if (shift > 63n) throw new Error('LEB128 value exceeds 64 bits');
  }
  throw new Error('Unterminated LEB128 sequence');
}

// ========== Run Length Encoding ==========

export function rleEncode(
  values: (bigint | null)[],
  encodeValue: (v: bigint) => Uint8Array
): Uint8Array {
  const chunks: Uint8Array[] = [];
  let i = 0;

  while (i < values.length) {
    if (values[i] === null) {
      let count = 0;
      while (i < values.length && values[i] === null) {
        count++;
        i++;
      }
      chunks.push(encodeLEB128(0n));
      chunks.push(encodeULEB128(BigInt(count)));
    } else {
      let runLen = 1;
      while (i + runLen < values.length && values[i + runLen] === values[i]) {
        runLen++;
      }

      if (runLen >= 2) {
        chunks.push(encodeLEB128(BigInt(runLen)));
        chunks.push(encodeValue(values[i]!));
        i += runLen;
      } else {
        let litLen = 0;
        let j = i;
        while (j < values.length && values[j] !== null) {
          if (j + 1 < values.length && values[j + 1] !== null && values[j + 1] === values[j]) {
            break;
          }
          litLen++;
          j++;
        }
        if (litLen === 0) litLen = 1;

        chunks.push(encodeLEB128(BigInt(-litLen)));
        for (let k = 0; k < litLen; k++) {
          chunks.push(encodeValue(values[i + k]!));
        }
        i += litLen;
      }
    }
  }

  return concatUint8Arrays(chunks);
}

export function rleDecode(
  data: Uint8Array,
  decodeValue: (data: Uint8Array, offset: number) => [bigint, number]
): (bigint | null)[] {
  const result: (bigint | null)[] = [];
  let pos = 0;

  while (pos < data.length) {
    const [length, lenBytes] = decodeLEB128(data, pos);
    pos += lenBytes;

    if (length === 0n) {
      const [count, countBytes] = decodeULEB128(data, pos);
      pos += countBytes;
      for (let i = 0n; i < count; i++) {
        result.push(null);
      }
    } else if (length > 0n) {
      const [value, valBytes] = decodeValue(data, pos);
      pos += valBytes;
      for (let i = 0n; i < length; i++) {
        result.push(value);
      }
    } else {
      const litCount = Number(-length);
      for (let i = 0; i < litCount; i++) {
        const [value, valBytes] = decodeValue(data, pos);
        pos += valBytes;
        result.push(value);
      }
    }
  }

  return result;
}

// ========== Column Types ==========

export function deltaEncode(values: bigint[]): Uint8Array {
  if (values.length === 0) return new Uint8Array(0);

  const deltas: (bigint | null)[] = [];
  let prev = 0n;
  for (const v of values) {
    deltas.push(v - prev);
    prev = v;
  }

  return rleEncode(deltas, encodeLEB128);
}

export function deltaDecode(data: Uint8Array): bigint[] {
  if (data.length === 0) return [];

  const deltas = rleDecode(data, decodeLEB128);
  const result: bigint[] = [];
  let acc = 0n;

  for (const d of deltas) {
    if (d === null) throw new Error('Null values not permitted in delta columns');
    acc += d;
    result.push(acc);
  }

  return result;
}

export function booleanEncode(values: boolean[]): Uint8Array {
  if (values.length === 0) return new Uint8Array(0);

  const chunks: Uint8Array[] = [];
  let current = false;
  let i = 0;

  while (i < values.length) {
    let count = 0;
    while (i < values.length && values[i] === current) {
      count++;
      i++;
    }
    chunks.push(encodeULEB128(BigInt(count)));
    current = !current;
  }

  return concatUint8Arrays(chunks);
}

export function booleanDecode(data: Uint8Array): boolean[] {
  if (data.length === 0) return [];

  const result: boolean[] = [];
  let current = false;
  let pos = 0;

  while (pos < data.length) {
    const [count, bytes] = decodeULEB128(data, pos);
    pos += bytes;
    for (let i = 0n; i < count; i++) {
      result.push(current);
    }
    current = !current;
  }

  return result;
}

export function stringEncode(values: (string | null)[]): Uint8Array {
  const chunks: Uint8Array[] = [];
  let i = 0;

  while (i < values.length) {
    if (values[i] === null) {
      let count = 0;
      while (i < values.length && values[i] === null) {
        count++;
        i++;
      }
      chunks.push(encodeLEB128(0n));
      chunks.push(encodeULEB128(BigInt(count)));
    } else {
      let runLen = 1;
      while (
        i + runLen < values.length &&
        values[i + runLen] !== null &&
        values[i + runLen] === values[i]
      ) {
        runLen++;
      }

      if (runLen >= 2) {
        chunks.push(encodeLEB128(BigInt(runLen)));
        const strBytes = new TextEncoder().encode(values[i]!);
        chunks.push(encodeULEB128(BigInt(strBytes.length)));
        if (strBytes.length > 0) chunks.push(strBytes);
        i += runLen;
      } else {
        let litLen = 0;
        let j = i;
        while (j < values.length && values[j] !== null) {
          if (
            j + 1 < values.length &&
            values[j + 1] !== null &&
            values[j + 1] === values[j]
          ) {
            break;
          }
          litLen++;
          j++;
        }
        if (litLen === 0) litLen = 1;

        chunks.push(encodeLEB128(BigInt(-litLen)));
        for (let k = 0; k < litLen; k++) {
          const strBytes = new TextEncoder().encode(values[i + k]!);
          chunks.push(encodeULEB128(BigInt(strBytes.length)));
          if (strBytes.length > 0) chunks.push(strBytes);
        }
        i += litLen;
      }
    }
  }

  return concatUint8Arrays(chunks);
}

export function stringDecode(data: Uint8Array): (string | null)[] {
  const result: (string | null)[] = [];
  let pos = 0;
  const decoder = new TextDecoder();

  while (pos < data.length) {
    const [length, lenBytes] = decodeLEB128(data, pos);
    pos += lenBytes;

    if (length === 0n) {
      const [count, countBytes] = decodeULEB128(data, pos);
      pos += countBytes;
      for (let i = 0n; i < count; i++) {
        result.push(null);
      }
    } else if (length > 0n) {
      const [strLen, strLenBytes] = decodeULEB128(data, pos);
      pos += strLenBytes;
      const str = decoder.decode(data.slice(pos, pos + Number(strLen)));
      pos += Number(strLen);
      for (let i = 0n; i < length; i++) {
        result.push(str);
      }
    } else {
      const litCount = Number(-length);
      for (let i = 0; i < litCount; i++) {
        const [strLen, strLenBytes] = decodeULEB128(data, pos);
        pos += strLenBytes;
        const str = decoder.decode(data.slice(pos, pos + Number(strLen)));
        pos += Number(strLen);
        result.push(str);
      }
    }
  }

  return result;
}

// ========== Column Specification ==========

export function encodeColumnSpec(id: number, type: number, deflate: boolean): number {
  return (id << 4) | (deflate ? 0x08 : 0) | (type & 0x07);
}

export function decodeColumnSpec(spec: number): { id: number; type: number; deflate: boolean } {
  const type = spec & 0x07;
  const deflate = (spec & 0x08) !== 0;
  const id = spec >> 4;
  return { id, type, deflate };
}

// ========== Value Metadata ==========

export function encodeValueMetadata(type: number, length: number): bigint {
  return BigInt((length << 4) | (type & 0x0f));
}

export function decodeValueMetadata(value: bigint): { type: number; length: number } {
  const type = Number(value & 0x0fn);
  const length = Number(value >> 4n);
  return { type, length };
}

// ========== Chunk Construction ==========

const MAGIC_BYTES = new Uint8Array([0x85, 0x6f, 0x4a, 0x83]);

export function computeChecksum(
  chunkType: number,
  chunkLengthBytes: Uint8Array,
  chunkContents: Uint8Array
): Uint8Array {
  const hash = createHash('sha256');
  hash.update(new Uint8Array([chunkType]));
  hash.update(chunkLengthBytes);
  hash.update(chunkContents);
  const digest = hash.digest();
  return new Uint8Array(digest.buffer, digest.byteOffset, 4);
}

export function constructChunk(chunkType: number, chunkContents: Uint8Array): Uint8Array {
  const lengthBytes = encodeULEB128(BigInt(chunkContents.length));
  const checksum = computeChecksum(chunkType, lengthBytes, chunkContents);

  const totalLen = MAGIC_BYTES.length + 4 + 1 + lengthBytes.length + chunkContents.length;
  const result = new Uint8Array(totalLen);
  let pos = 0;

  result.set(MAGIC_BYTES, pos); pos += MAGIC_BYTES.length;
  result.set(checksum, pos); pos += 4;
  result[pos] = chunkType; pos += 1;
  result.set(lengthBytes, pos); pos += lengthBytes.length;
  result.set(chunkContents, pos);

  return result;
}

export function parseChunkHeader(data: Uint8Array): {
  chunkType: number;
  checksum: Uint8Array;
  chunkLength: bigint;
  headerSize: number;
  valid: boolean;
} {
  for (let i = 0; i < 4; i++) {
    if (data[i] !== MAGIC_BYTES[i]) {
      throw new Error('Invalid magic bytes');
    }
  }

  const checksum = data.slice(4, 8);
  const chunkType = data[8];
  const [chunkLength, lenBytes] = decodeULEB128(data, 9);
  const headerSize = 9 + lenBytes;

  const chunkContents = data.slice(headerSize, headerSize + Number(chunkLength));
  const lengthBytes = data.slice(9, headerSize);
  const expectedChecksum = computeChecksum(chunkType, lengthBytes, chunkContents);

  let valid = true;
  for (let i = 0; i < 4; i++) {
    if (checksum[i] !== expectedChecksum[i]) {
      valid = false;
      break;
    }
  }

  return { chunkType, checksum, chunkLength, headerSize, valid };
}

export function createEmptyDocument(): Uint8Array {
  const contents = new Uint8Array([0x00, 0x00, 0x00, 0x00]);
  return constructChunk(0x00, contents);
}

// ========== Utility ==========

function concatUint8Arrays(arrays: Uint8Array[]): Uint8Array {
  const totalLen = arrays.reduce((sum, arr) => sum + arr.length, 0);
  const result = new Uint8Array(totalLen);
  let pos = 0;
  for (const arr of arrays) {
    result.set(arr, pos);
    pos += arr.length;
  }
  return result;
}

export { MAGIC_BYTES };
'''

with open(CODEC_PATH, 'w') as f:
    f.write(FIXED_CODEC)
print(f'Wrote fixed codec to {CODEC_PATH}')

if not os.path.exists(PKG_PATH):
    pkg = {
        "name": "automerge-codec",
        "version": "1.0.0",
        "type": "module",
        "devDependencies": {
            "tsx": "^4.7.0",
            "typescript": "^5.3.0",
            "@types/node": "^20.11.0"
        }
    }
    with open(PKG_PATH, 'w') as f:
        json.dump(pkg, f, indent=2)
        f.write('\n')
    print(f'Wrote {PKG_PATH}')

if not os.path.exists(TSC_PATH):
    tsc = {
        "compilerOptions": {
            "target": "ES2022",
            "module": "ES2022",
            "moduleResolution": "node16",
            "strict": True,
            "esModuleInterop": True,
            "outDir": "./dist",
            "rootDir": "./src",
            "declaration": True,
            "sourceMap": True
        },
        "include": ["src/**/*.ts"]
    }
    with open(TSC_PATH, 'w') as f:
        json.dump(tsc, f, indent=2)
        f.write('\n')
    print(f'Wrote {TSC_PATH}')

print('All fixes and implementations applied successfully.')

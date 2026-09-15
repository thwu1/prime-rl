
// Automerge Binary Document Format — Columnar Encoding Codec
// Partially implements encoding/decoding for the Automerge storage format's
// variable-length integers, RLE compression, column types,
// column specifications, value metadata, and chunk construction.

import { createHash } from 'crypto';

// ========== LEB128 Encoding ==========

/** Encode a non-negative integer as an unsigned LEB128 byte sequence. */
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

/** Decode a uLEB128 from bytes at the given offset. Returns [value, bytesConsumed]. */
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

/** Encode a signed integer as a signed LEB128 byte sequence (two's complement). */
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

/** Decode a signed LEB128 from bytes at the given offset. Returns [value, bytesConsumed]. */
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

/**
 * RLE-encode an array of nullable values.
 * Supports compressed runs (repeated values) and null runs.
 */
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
      // Count consecutive equal values
      let runLen = 1;
      while (i + runLen < values.length && values[i + runLen] === values[i]) {
        runLen++;
      }
      // Emit as compressed run
      chunks.push(encodeLEB128(BigInt(runLen)));
      chunks.push(encodeValue(values[i]!));
      i += runLen;
    }
  }

  return concatUint8Arrays(chunks);
}

/**
 * Decode an RLE-encoded byte sequence.
 */
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
      // Null run
      const [count, countBytes] = decodeULEB128(data, pos);
      pos += countBytes;
      for (let i = 0n; i < count; i++) {
        result.push(null);
      }
    } else if (length > 0n) {
      // Compressed run
      const [value, valBytes] = decodeValue(data, pos);
      pos += valBytes;
      for (let i = 0n; i < length; i++) {
        result.push(value);
      }
    } else {
      throw new Error(`Unsupported RLE run type with length ${length}`);
    }
  }

  return result;
}

// ========== Column Types ==========

/**
 * Delta column encoder.
 * Computes successive differences and RLE-encodes them as signed integers.
 */
export function deltaEncode(values: bigint[]): Uint8Array {
  throw new Error('deltaEncode: not yet implemented');
}

/**
 * Delta column decoder.
 * Decodes RLE-compressed signed deltas and reconstructs original values.
 */
export function deltaDecode(data: Uint8Array): bigint[] {
  throw new Error('deltaDecode: not yet implemented');
}

/**
 * Boolean column encoder.
 * Encodes as alternating run-length counts. Each uLEB count says how many
 * consecutive values match the current state before toggling.
 */
export function booleanEncode(values: boolean[]): Uint8Array {
  if (values.length === 0) return new Uint8Array(0);

  const chunks: Uint8Array[] = [];
  let current = true;
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

/**
 * Boolean column decoder.
 * Reads alternating uLEB counts to reconstruct boolean values.
 */
export function booleanDecode(data: Uint8Array): boolean[] {
  if (data.length === 0) return [];

  const result: boolean[] = [];
  let current = true;
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

/**
 * String column encoder.
 * RLE-encodes length-prefixed UTF-8 strings with null run support.
 */
export function stringEncode(values: (string | null)[]): Uint8Array {
  throw new Error('stringEncode: not yet implemented');
}

/**
 * String column decoder.
 * Decodes RLE-compressed length-prefixed UTF-8 strings.
 */
export function stringDecode(data: Uint8Array): (string | null)[] {
  throw new Error('stringDecode: not yet implemented');
}

// ========== Column Specification ==========

/**
 * Encode a column specification as a uLEB32 bitfield.
 * Layout: lowest 3 bits = column type, bit 3 = deflate flag, remaining = column ID.
 */
export function encodeColumnSpec(id: number, type: number, deflate: boolean): number {
  return (id << 4) | (deflate ? 0x08 : 0) | (type & 0x07);
}

/**
 * Decode a column specification bitfield.
 * Extracts the column type, deflate flag, and column ID.
 */
export function decodeColumnSpec(spec: number): { id: number; type: number; deflate: boolean } {
  const type = spec & 0x07;
  const deflate = (spec & 0x08) !== 0;
  const id = spec >> 3;
  return { id, type, deflate };
}

// ========== Value Metadata ==========

/**
 * Encode value metadata as a packed integer.
 * Combines the value type tag and byte length into a single value.
 */
export function encodeValueMetadata(type: number, length: number): bigint {
  return BigInt((type << 4) | (length & 0x0f));
}

/**
 * Decode value metadata from a packed integer.
 * Extracts the value type tag and byte length.
 */
export function decodeValueMetadata(value: bigint): { type: number; length: number } {
  const length = Number(value & 0x0fn);
  const type = Number(value >> 4n);
  return { type, length };
}

// ========== Chunk Construction ==========

/** Automerge magic bytes that begin every document/chunk. */
const MAGIC_BYTES = new Uint8Array([0x85, 0x6f, 0x4a, 0x83]);

/**
 * Compute the 4-byte checksum for a chunk.
 * The checksum is the first 4 bytes of the SHA-256 hash of the relevant fields.
 */
export function computeChecksum(
  chunkType: number,
  chunkLengthBytes: Uint8Array,
  chunkContents: Uint8Array
): Uint8Array {
  const hash = createHash('sha256');
  hash.update(chunkContents);
  const digest = hash.digest();
  return new Uint8Array(digest.buffer, digest.byteOffset, 4);
}

/**
 * Construct a complete chunk: magic bytes + checksum + type + length + contents.
 */
export function constructChunk(chunkType: number, chunkContents: Uint8Array): Uint8Array {
  throw new Error('constructChunk: not yet implemented');
}

/**
 * Parse a chunk header from binary data.
 * Validates magic bytes and checks checksum integrity.
 */
export function parseChunkHeader(data: Uint8Array): {
  chunkType: number;
  checksum: Uint8Array;
  chunkLength: bigint;
  headerSize: number;
  valid: boolean;
} {
  throw new Error('parseChunkHeader: not yet implemented');
}

/**
 * Create the binary representation of an empty Automerge document.
 * An empty document has zero actors, zero heads, zero change columns,
 * and zero operation columns.
 */
export function createEmptyDocument(): Uint8Array {
  throw new Error('createEmptyDocument: not yet implemented');
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

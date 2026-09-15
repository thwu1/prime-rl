
/**
 * Encode an unsigned integer as ULEB128.
 * Returns an array of bytes.
 */
export function encodeULEB128(value: number): number[] {
  if (value < 0) throw new Error("Cannot encode negative value as ULEB128");
  const result: number[] = [];
  do {
    let byte = value & 0x7f;
    value = Math.floor(value / 128);
    if (value !== 0) byte |= 0x80;
    result.push(byte);
  } while (value !== 0);
  return result;
}

/**
 * Decode a ULEB128 integer from a byte array.
 * Returns [value, bytesConsumed].
 */
export function decodeULEB128(data: Uint8Array, offset: number = 0): [number, number] {
  let result = 0;
  let shift = 0;
  let pos = offset;
  while (true) {
    if (pos >= data.length) throw new Error("Unexpected end of ULEB128 data");
    const byte = data[pos];
    result += (byte & 0x7f) * Math.pow(2, shift);
    shift += 7;
    pos++;
    if ((byte & 0x80) === 0) break;
    if (shift >= 70) throw new Error("ULEB128 too long");
  }
  return [result, pos - offset];
}

/**
 * Encode a signed integer as SLEB128.
 * Returns an array of bytes.
 */
export function encodeSLEB128(value: number): number[] {
  const result: number[] = [];
  let more = true;
  while (more) {
    let byte = value & 0x7f;
    value = Math.floor(value / 128);
    const signBitSet = (byte & 0x40) !== 0;
    if ((value === 0 && !signBitSet) || (value === -1 && signBitSet)) {
      more = false;
    } else {
      byte |= 0x80;
    }
    result.push(byte);
  }
  return result;
}

/**
 * Decode a SLEB128 integer from a byte array.
 * Returns [value, bytesConsumed].
 */
export function decodeSLEB128(data: Uint8Array, offset: number = 0): [number, number] {
  let result = 0;
  let shift = 0;
  let pos = offset;
  let byte: number;
  do {
    if (pos >= data.length) throw new Error("Unexpected end of SLEB128 data");
    byte = data[pos];
    result += (byte & 0x7f) * Math.pow(2, shift);
    shift += 7;
    pos++;
  } while ((byte & 0x80) !== 0);
  return [result, pos - offset];
}

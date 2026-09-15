
/**
 * lib0-compatible binary encoder with variable-length integer support.
 * Encodes in little-endian order, compatible with Protocol Buffers varint format.
 */
export class Encoder {
  private buf: number[] = [];

  write(byte: number): void {
    this.buf.push(byte & 0xFF);
  }

  /**
   * Write a variable-length unsigned integer (up to 32 bits).
   * Each byte uses 7 data bits and 1 continuation bit (MSB).
   */
  writeVarUint(num: number): void {
    while (num > 0x7F) {
      this.write(0x80 | (0x7F & num));
      num = (num >>> 7);
    }
    this.write(0x7F & num);
  }

  /**
   * Write a variable-length string (length-prefixed with varuint, then UTF-8 bytes).
   */
  writeVarString(str: string): void {
    const encoded = Buffer.from(str, 'utf-8');
    this.writeVarUint(encoded.length);
    for (const b of encoded) {
      this.write(b);
    }
  }

  toUint8Array(): Uint8Array {
    return new Uint8Array(this.buf);
  }
}

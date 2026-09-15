
/**
 * lib0-compatible binary decoder with variable-length integer support.
 */
export class Decoder {
  public arr: Uint8Array;
  public pos: number = 0;

  constructor(arr: Uint8Array) {
    this.arr = arr;
  }

  readUint8(): number {
    return this.arr[this.pos++];
  }

  /**
   * Read a variable-length unsigned integer.
   * Each byte uses 7 data bits and 1 continuation bit (MSB).
   */
  readVarUint(): number {
    let num = 0;
    let len = 0;
    while (true) {
      const r = this.arr[this.pos++];
      num = num | ((r & 0x7F) << len);
      len += 7;
      if (r < 0x80) {
        return num >>> 0;
      }
      if (len > 35) {
        throw new Error('VarUint out of range');
      }
    }
  }

  /**
   * Read a variable-length string (length-prefixed varuint, then UTF-8 bytes).
   */
  readVarString(): string {
    const len = this.readVarUint();
    const bytes = this.arr.slice(this.pos, this.pos + len);
    this.pos += len;
    return Buffer.from(bytes).toString('utf-8');
  }

  hasContent(): boolean {
    return this.pos < this.arr.length;
  }
}

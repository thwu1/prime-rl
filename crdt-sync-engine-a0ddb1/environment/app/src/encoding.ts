
/**
 * lib0-compatible binary encoder.
 *
 * Byte-level operations (writeByte, toUint8Array) are functional.
 * All variable-length and higher-level methods must be implemented.
 */
export class Encoder {
  public data: number[] = [];

  /** Write a single byte (0-255). */
  writeByte(b: number): void {
    this.data.push(b & 0xFF);
  }

  /** Write a variable-length unsigned integer (lib0 format). */
  writeVarUint(num: number): void {
    throw new Error("Not implemented: writeVarUint");
  }

  /** Write a variable-length signed integer (lib0 format). */
  writeVarInt(num: number): void {
    throw new Error("Not implemented: writeVarInt");
  }

  /** Write a variable-length UTF-8 string. */
  writeVarString(str: string): void {
    throw new Error("Not implemented: writeVarString");
  }

  /** Write a variable-length Uint8Array. */
  writeVarUint8Array(arr: Uint8Array): void {
    throw new Error("Not implemented: writeVarUint8Array");
  }

  /** Write a type-tagged value (lib0 Any format). */
  writeAny(data: any): void {
    throw new Error("Not implemented: writeAny");
  }

  /** Return all written bytes as a Uint8Array. */
  toUint8Array(): Uint8Array {
    return new Uint8Array(this.data);
  }
}

/**
 * lib0-compatible binary decoder.
 *
 * Byte-level operations (readByte, hasContent) are functional.
 * All variable-length and higher-level methods must be implemented.
 */
export class Decoder {
  public arr: Uint8Array;
  public pos: number = 0;

  constructor(arr: Uint8Array) {
    this.arr = arr;
  }

  /** Returns true if there are more bytes to read. */
  hasContent(): boolean {
    return this.pos < this.arr.length;
  }

  /** Read a single byte. Throws if at end of array. */
  readByte(): number {
    if (this.pos >= this.arr.length) {
      throw new Error("Unexpected end of array");
    }
    return this.arr[this.pos++];
  }

  /** Read a variable-length unsigned integer (lib0 format). */
  readVarUint(): number {
    throw new Error("Not implemented: readVarUint");
  }

  /** Read a variable-length signed integer (lib0 format). */
  readVarInt(): number {
    throw new Error("Not implemented: readVarInt");
  }

  /** Read a variable-length UTF-8 string. */
  readVarString(): string {
    throw new Error("Not implemented: readVarString");
  }

  /** Read a variable-length Uint8Array. */
  readVarUint8Array(): Uint8Array {
    throw new Error("Not implemented: readVarUint8Array");
  }

  /** Read a type-tagged value (lib0 Any format). */
  readAny(): any {
    throw new Error("Not implemented: readAny");
  }
}

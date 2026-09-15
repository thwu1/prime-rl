
/**
 * lib0-compatible binary encoder/decoder.
 * Implements variable-length integer encoding, type-tagged Any encoding,
 * and string/byte-array encoding following the lib0 specification.
 */

const floatTestBed = new DataView(new ArrayBuffer(4));
function isFloat32(num: number): boolean {
  floatTestBed.setFloat32(0, num);
  return floatTestBed.getFloat32(0) === num;
}

export class Encoder {
  public data: number[] = [];

  writeByte(b: number): void {
    this.data.push(b & 0xFF);
  }

  writeUint8Array(arr: Uint8Array): void {
    for (let i = 0; i < arr.length; i++) {
      this.data.push(arr[i]);
    }
  }

  writeVarUint(num: number): void {
    while (num > 0x7F) {
      this.writeByte(0x80 | (num & 0x7F));
      num = Math.floor(num / 128);
    }
    this.writeByte(num & 0x7F);
  }

  writeVarInt(num: number): void {
    const isNegative = num < 0;
    if (isNegative) num = -num;
    const firstBits = num & 0x3F;
    const rest = Math.floor(num / 64);
    const signBit = isNegative ? 0x40 : 0;
    const contBit = rest > 0 ? 0x80 : 0;
    this.writeByte(contBit | signBit | firstBits);
    if (rest > 0) {
      this.writeVarUint(rest);
    }
  }

  writeVarString(str: string): void {
    const bytes = Buffer.from(str, 'utf-8');
    this.writeVarUint(bytes.length);
    this.writeUint8Array(bytes);
  }

  writeVarUint8Array(arr: Uint8Array): void {
    this.writeVarUint(arr.length);
    this.writeUint8Array(arr);
  }

  writeFloat32(num: number): void {
    const buf = Buffer.alloc(4);
    buf.writeFloatBE(num, 0);
    this.writeUint8Array(buf);
  }

  writeFloat64(num: number): void {
    const buf = Buffer.alloc(8);
    buf.writeDoubleBE(num, 0);
    this.writeUint8Array(buf);
  }

  writeAny(data: any): void {
    if (data === undefined) {
      this.writeByte(127);
    } else if (data === null) {
      this.writeByte(126);
    } else if (typeof data === 'number') {
      if (Number.isInteger(data) && Math.abs(data) <= 0x7FFFFFFF) {
        this.writeByte(125);
        this.writeVarInt(data);
      } else if (isFloat32(data)) {
        this.writeByte(124);
        this.writeFloat32(data);
      } else {
        this.writeByte(123);
        this.writeFloat64(data);
      }
    } else if (typeof data === 'boolean') {
      this.writeByte(data ? 120 : 121);
    } else if (typeof data === 'string') {
      this.writeByte(119);
      this.writeVarString(data);
    } else if (data instanceof Uint8Array) {
      this.writeByte(116);
      this.writeVarUint8Array(data);
    } else if (Array.isArray(data)) {
      this.writeByte(117);
      this.writeVarUint(data.length);
      for (const item of data) {
        this.writeAny(item);
      }
    } else if (typeof data === 'object') {
      this.writeByte(118);
      const keys = Object.keys(data);
      this.writeVarUint(keys.length);
      for (const key of keys) {
        this.writeVarString(key);
        this.writeAny(data[key]);
      }
    } else {
      this.writeByte(127);
    }
  }

  toUint8Array(): Uint8Array {
    return new Uint8Array(this.data);
  }
}

export class Decoder {
  public arr: Uint8Array;
  public pos: number = 0;

  constructor(arr: Uint8Array) {
    this.arr = arr;
  }

  hasContent(): boolean {
    return this.pos < this.arr.length;
  }

  readByte(): number {
    if (this.pos >= this.arr.length) {
      throw new Error('Unexpected end of array');
    }
    return this.arr[this.pos++];
  }

  readUint8Array(len: number): Uint8Array {
    const view = this.arr.slice(this.pos, this.pos + len);
    this.pos += len;
    return view;
  }

  readVarUint(): number {
    let num = 0;
    let mult = 1;
    while (true) {
      const r = this.readByte();
      num += (r & 0x7F) * mult;
      mult *= 128;
      if ((r & 0x80) === 0) return num;
    }
  }

  readVarInt(): number {
    const r = this.readByte();
    const sign = (r & 0x40) > 0 ? -1 : 1;
    let num = r & 0x3F;
    if ((r & 0x80) === 0) return sign * num;
    let mult = 64;
    while (true) {
      const b = this.readByte();
      num += (b & 0x7F) * mult;
      mult *= 128;
      if ((b & 0x80) === 0) return sign * num;
    }
  }

  readVarString(): string {
    const len = this.readVarUint();
    const bytes = this.readUint8Array(len);
    return Buffer.from(bytes).toString('utf-8');
  }

  readVarUint8Array(): Uint8Array {
    const len = this.readVarUint();
    return this.readUint8Array(len);
  }

  readFloat32(): number {
    const bytes = this.readUint8Array(4);
    return Buffer.from(bytes).readFloatBE(0);
  }

  readFloat64(): number {
    const bytes = this.readUint8Array(8);
    return Buffer.from(bytes).readDoubleBE(0);
  }

  readAny(): any {
    const tag = this.readByte();
    switch (tag) {
      case 127: return undefined;
      case 126: return null;
      case 125: return this.readVarInt();
      case 124: return this.readFloat32();
      case 123: return this.readFloat64();
      case 121: return false;
      case 120: return true;
      case 119: return this.readVarString();
      case 118: {
        const len = this.readVarUint();
        const obj: any = {};
        for (let i = 0; i < len; i++) {
          const key = this.readVarString();
          obj[key] = this.readAny();
        }
        return obj;
      }
      case 117: {
        const len = this.readVarUint();
        const arr: any[] = [];
        for (let i = 0; i < len; i++) {
          arr.push(this.readAny());
        }
        return arr;
      }
      case 116: return this.readVarUint8Array();
      default: throw new Error(`Unknown any type tag: ${tag}`);
    }
  }
}

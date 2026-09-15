#!/usr/bin/env python3
"""
Solve the Automerge columnar codec task by fixing all bugs
and implementing all missing components.
"""

import os
import json

def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

# --- Restore tsconfig.json ---
tsconfig = {
    "compilerOptions": {
        "target": "ES2020",
        "module": "commonjs",
        "moduleResolution": "node",
        "esModuleInterop": True,
        "strict": True,
        "outDir": "./dist",
        "rootDir": "./src",
        "skipLibCheck": True
    },
    "files": [
        "src/globals.d.ts",
        "src/leb128.ts",
        "src/rle.ts",
        "src/delta.ts",
        "src/boolean.ts",
        "src/columns.ts",
        "src/cli.ts"
    ]
}
write_file('/app/tsconfig.json', json.dumps(tsconfig, indent=2) + '\n')

# --- Restore globals.d.ts ---
globals_dts = '''\
// Node.js global declarations
declare var process: {
  argv: string[];
  exit(code: number): never;
};
'''
write_file('/app/src/globals.d.ts', globals_dts)

# --- Fix: leb128.ts - Add sign extension to decodeSLEB128 ---
leb128_ts = '''\

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
  // Sign extension: if bit 6 of the last byte is set, the value is negative
  if ((byte & 0x40) !== 0) {
    result -= Math.pow(2, shift);
  }
  return [result, pos - offset];
}
'''

# --- Fix + Implement: rle.ts ---
rle_ts = '''\

import { encodeSLEB128, decodeSLEB128, encodeULEB128, decodeULEB128 } from './leb128';

enum RleState {
  Empty,
  InitialNullRun,
  NullRun,
  LoneVal,
  Run,
  LiteralRun,
}

export class RleEncoder {
  private buf: number[] = [];
  private state: RleState = RleState.Empty;
  private currentValue: number = 0;
  private count: number = 0;
  private litRun: number[] = [];

  constructor(private signed: boolean = false) {}

  private encodeValue(v: number): number[] {
    return this.signed ? encodeSLEB128(v) : encodeULEB128(v);
  }

  private flushRun(value: number, count: number): void {
    this.buf.push(...encodeSLEB128(count));
    this.buf.push(...this.encodeValue(value));
  }

  private flushNullRun(count: number): void {
    this.buf.push(...encodeSLEB128(0));
    this.buf.push(...encodeULEB128(count));
  }

  private flushLitRun(values: number[]): void {
    this.buf.push(...encodeSLEB128(-values.length));
    for (const v of values) {
      this.buf.push(...this.encodeValue(v));
    }
  }

  appendNull(): void {
    switch (this.state) {
      case RleState.Empty:
        this.state = RleState.InitialNullRun;
        this.count = 1;
        break;
      case RleState.InitialNullRun:
        this.count++;
        break;
      case RleState.NullRun:
        this.count++;
        break;
      case RleState.LoneVal:
        this.flushLitRun([this.currentValue]);
        this.state = RleState.NullRun;
        this.count = 1;
        break;
      case RleState.Run:
        this.flushRun(this.currentValue, this.count);
        this.state = RleState.NullRun;
        this.count = 1;
        break;
      case RleState.LiteralRun:
        this.litRun.push(this.currentValue);
        this.flushLitRun(this.litRun);
        this.litRun = [];
        this.state = RleState.NullRun;
        this.count = 1;
        break;
    }
  }

  appendValue(value: number): void {
    switch (this.state) {
      case RleState.Empty:
        this.state = RleState.LoneVal;
        this.currentValue = value;
        break;
      case RleState.LoneVal:
        if (this.currentValue === value) {
          this.state = RleState.Run;
          this.count = 2;
        } else {
          this.litRun = [this.currentValue];
          this.state = RleState.LiteralRun;
          this.currentValue = value;
        }
        break;
      case RleState.Run:
        if (this.currentValue === value) {
          this.count++;
        } else {
          this.flushRun(this.currentValue, this.count);
          this.state = RleState.LoneVal;
          this.currentValue = value;
        }
        break;
      case RleState.LiteralRun:
        if (this.currentValue === value) {
          this.flushLitRun(this.litRun);
          this.litRun = [];
          this.state = RleState.Run;
          this.currentValue = value;
          this.count = 2;
        } else {
          this.litRun.push(this.currentValue);
          this.currentValue = value;
        }
        break;
      case RleState.NullRun:
      case RleState.InitialNullRun:
        this.flushNullRun(this.count);
        this.state = RleState.LoneVal;
        this.currentValue = value;
        break;
    }
  }

  append(value: number | null): void {
    if (value === null || value === undefined) {
      this.appendNull();
    } else {
      this.appendValue(value);
    }
  }

  finish(): number[] {
    switch (this.state) {
      case RleState.Empty:
      case RleState.InitialNullRun:
        break;
      case RleState.NullRun:
        this.flushNullRun(this.count);
        break;
      case RleState.LoneVal:
        // Fix: flush lone value as a literal run of length 1
        this.flushLitRun([this.currentValue]);
        break;
      case RleState.Run:
        this.flushRun(this.currentValue, this.count);
        break;
      case RleState.LiteralRun:
        this.litRun.push(this.currentValue);
        this.flushLitRun(this.litRun);
        break;
    }
    return this.buf;
  }
}

export class RleDecoder {
  private data: Uint8Array;
  private pos: number = 0;
  private count: number = 0;
  private literal: boolean = false;
  private lastValue: number | null = null;

  constructor(data: Uint8Array, private signed: boolean = false) {
    this.data = data;
  }

  private decodeValue(): number {
    if (this.signed) {
      const [value, len] = decodeSLEB128(this.data, this.pos);
      this.pos += len;
      return value;
    } else {
      const [value, len] = decodeULEB128(this.data, this.pos);
      this.pos += len;
      return value;
    }
  }

  done(): boolean {
    return this.pos >= this.data.length && this.count === 0;
  }

  next(): (number | null) | undefined {
    while (this.count === 0) {
      if (this.pos >= this.data.length) return undefined;

      const [count, countLen] = decodeSLEB128(this.data, this.pos);
      this.pos += countLen;

      if (count > 0) {
        // Value run: read one value, repeat count times
        this.count = count;
        this.lastValue = this.decodeValue();
        this.literal = false;
      } else if (count < 0) {
        // Literal run: |count| distinct values follow
        this.count = -count;
        this.literal = true;
      } else {
        // Null run: read ULEB128 count of nulls
        const [nullCount, nullLen] = decodeULEB128(this.data, this.pos);
        this.pos += nullLen;
        this.count = nullCount;
        this.lastValue = null;
        this.literal = false;
      }
    }

    this.count--;
    if (this.literal) {
      return this.decodeValue();
    } else {
      return this.lastValue;
    }
  }

  readAll(): (number | null)[] {
    const result: (number | null)[] = [];
    while (!this.done()) {
      const val = this.next();
      if (val === undefined) break;
      result.push(val);
    }
    return result;
  }
}
'''

# --- Implement: delta.ts ---
delta_ts = '''\

import { RleEncoder, RleDecoder } from './rle';

export class DeltaEncoder {
  private rle: RleEncoder;
  private absoluteValue: number = 0;

  constructor() {
    this.rle = new RleEncoder(true);
  }

  append(value: number | null): void {
    if (value === null || value === undefined) {
      this.rle.append(null);
    } else {
      const delta = value - this.absoluteValue;
      this.rle.append(delta);
      this.absoluteValue = value;
    }
  }

  finish(): number[] {
    return this.rle.finish();
  }
}

export class DeltaDecoder {
  private rle: RleDecoder;
  private absoluteValue: number = 0;

  constructor(data: Uint8Array) {
    this.rle = new RleDecoder(data, true);
  }

  next(): (number | null) | undefined {
    const delta = this.rle.next();
    if (delta === undefined) return undefined;
    if (delta === null) return null;
    this.absoluteValue += delta;
    return this.absoluteValue;
  }

  readAll(): (number | null)[] {
    const result: (number | null)[] = [];
    while (true) {
      const val = this.next();
      if (val === undefined) break;
      result.push(val);
    }
    return result;
  }
}
'''

# --- Implement: boolean.ts ---
boolean_ts = '''\

import { encodeULEB128, decodeULEB128 } from './leb128';

export class BooleanEncoder {
  private counts: number[] = [];
  private currentPolarity: boolean = false;
  private currentCount: number = 0;

  append(value: boolean): void {
    if (value === this.currentPolarity) {
      this.currentCount++;
    } else {
      this.counts.push(this.currentCount);
      this.currentPolarity = value;
      this.currentCount = 1;
    }
  }

  finish(): number[] {
    if (this.currentCount > 0 || this.counts.length > 0) {
      this.counts.push(this.currentCount);
    }
    const result: number[] = [];
    for (const count of this.counts) {
      result.push(...encodeULEB128(count));
    }
    return result;
  }
}

export class BooleanDecoder {
  private data: Uint8Array;
  private pos: number = 0;
  private currentPolarity: boolean = false;
  private remaining: number = 0;

  constructor(data: Uint8Array) {
    this.data = data;
  }

  next(): boolean | undefined {
    while (this.remaining === 0) {
      if (this.pos >= this.data.length) return undefined;
      const [count, bytesRead] = decodeULEB128(this.data, this.pos);
      this.pos += bytesRead;
      this.remaining = count;
      if (this.remaining === 0) {
        this.currentPolarity = !this.currentPolarity;
      }
    }
    const value = this.currentPolarity;
    this.remaining--;
    if (this.remaining === 0) {
      this.currentPolarity = !this.currentPolarity;
    }
    return value;
  }

  readAll(): boolean[] {
    const result: boolean[] = [];
    while (true) {
      const val = this.next();
      if (val === undefined) break;
      result.push(val);
    }
    return result;
  }
}
'''

# --- Implement: columns.ts ---
columns_ts = '''\

import { encodeULEB128, decodeULEB128 } from './leb128';
import { RleEncoder, RleDecoder } from './rle';
import { DeltaEncoder, DeltaDecoder } from './delta';
import { BooleanEncoder, BooleanDecoder } from './boolean';

export enum ColumnType {
  UINT_RLE = 0,
  INT_RLE = 1,
  DELTA = 2,
  BOOLEAN = 3,
}

export interface ColumnData {
  id: number;
  type: ColumnType;
  values: (number | boolean | null)[];
}

function encodeColumn(type: ColumnType, values: (number | boolean | null)[]): number[] {
  switch (type) {
    case ColumnType.UINT_RLE: {
      const enc = new RleEncoder(false);
      for (const v of values) enc.append(v as number | null);
      return enc.finish();
    }
    case ColumnType.INT_RLE: {
      const enc = new RleEncoder(true);
      for (const v of values) enc.append(v as number | null);
      return enc.finish();
    }
    case ColumnType.DELTA: {
      const enc = new DeltaEncoder();
      for (const v of values) enc.append(v as number | null);
      return enc.finish();
    }
    case ColumnType.BOOLEAN: {
      const enc = new BooleanEncoder();
      for (const v of values) enc.append(v as boolean);
      return enc.finish();
    }
  }
}

function decodeColumn(type: ColumnType, data: Uint8Array): (number | boolean | null)[] {
  switch (type) {
    case ColumnType.UINT_RLE:
      return new RleDecoder(data, false).readAll();
    case ColumnType.INT_RLE:
      return new RleDecoder(data, true).readAll();
    case ColumnType.DELTA:
      return new DeltaDecoder(data).readAll();
    case ColumnType.BOOLEAN:
      return new BooleanDecoder(data).readAll();
  }
}

export function serializeColumns(columns: ColumnData[]): number[] {
  const sorted = [...columns].sort((a, b) => a.id - b.id);
  const encoded = sorted.map(col => ({
    id: col.id,
    type: col.type,
    data: encodeColumn(col.type, col.values),
  }));

  const result: number[] = [];
  result.push(...encodeULEB128(encoded.length));

  for (const col of encoded) {
    result.push(...encodeULEB128(col.id));
    result.push(...encodeULEB128(col.type));
    result.push(...encodeULEB128(col.data.length));
  }

  for (const col of encoded) {
    result.push(...col.data);
  }

  return result;
}

export function deserializeColumns(data: Uint8Array): ColumnData[] {
  let pos = 0;

  const [numCols, numColsLen] = decodeULEB128(data, pos);
  pos += numColsLen;

  const headers: {id: number, type: ColumnType, dataLen: number}[] = [];
  for (let i = 0; i < numCols; i++) {
    const [id, idLen] = decodeULEB128(data, pos);
    pos += idLen;
    const [type, typeLen] = decodeULEB128(data, pos);
    pos += typeLen;
    const [dataLen, dataLenLen] = decodeULEB128(data, pos);
    pos += dataLenLen;
    headers.push({ id, type: type as ColumnType, dataLen });
  }

  const result: ColumnData[] = [];
  for (const header of headers) {
    const colData = data.slice(pos, pos + header.dataLen);
    pos += header.dataLen;
    const values = decodeColumn(header.type, colData);
    result.push({ id: header.id, type: header.type, values });
  }

  return result;
}
'''

# --- Restore cli.ts ---
cli_ts = '''\

import { encodeULEB128, decodeULEB128, encodeSLEB128, decodeSLEB128 } from './leb128';
import { RleEncoder, RleDecoder } from './rle';
import { DeltaEncoder, DeltaDecoder } from './delta';
import { BooleanEncoder, BooleanDecoder } from './boolean';
import { serializeColumns, deserializeColumns, ColumnData } from './columns';

function toHex(bytes: number[]): string {
  return bytes.map(b => b.toString(16).padStart(2, '0')).join(' ');
}

function fromHex(hex: string): Uint8Array {
  const trimmed = hex.trim();
  if (trimmed === '') return new Uint8Array(0);
  const bytes = trimmed.split(/\\s+/).map(s => parseInt(s, 16));
  return new Uint8Array(bytes);
}

const [command, ...args] = process.argv.slice(2);

try {
  switch (command) {
    case 'encode-uleb': {
      const value = parseInt(args[0]);
      console.log(toHex(encodeULEB128(value)));
      break;
    }
    case 'decode-uleb': {
      const data = fromHex(args[0]);
      const [value] = decodeULEB128(data);
      console.log(value);
      break;
    }
    case 'encode-sleb': {
      const value = parseInt(args[0]);
      console.log(toHex(encodeSLEB128(value)));
      break;
    }
    case 'decode-sleb': {
      const data = fromHex(args[0]);
      const [value] = decodeSLEB128(data);
      console.log(value);
      break;
    }
    case 'encode-rle-uint': {
      const arr = JSON.parse(args[0]) as (number | null)[];
      const enc = new RleEncoder(false);
      for (const v of arr) enc.append(v);
      console.log(toHex(enc.finish()));
      break;
    }
    case 'decode-rle-uint': {
      const data = fromHex(args[0]);
      const dec = new RleDecoder(data, false);
      console.log(JSON.stringify(dec.readAll()));
      break;
    }
    case 'encode-rle-int': {
      const arr = JSON.parse(args[0]) as (number | null)[];
      const enc = new RleEncoder(true);
      for (const v of arr) enc.append(v);
      console.log(toHex(enc.finish()));
      break;
    }
    case 'decode-rle-int': {
      const data = fromHex(args[0]);
      const dec = new RleDecoder(data, true);
      console.log(JSON.stringify(dec.readAll()));
      break;
    }
    case 'encode-delta': {
      const arr = JSON.parse(args[0]) as (number | null)[];
      const enc = new DeltaEncoder();
      for (const v of arr) enc.append(v);
      console.log(toHex(enc.finish()));
      break;
    }
    case 'decode-delta': {
      const data = fromHex(args[0]);
      const dec = new DeltaDecoder(data);
      console.log(JSON.stringify(dec.readAll()));
      break;
    }
    case 'encode-bool': {
      const arr = JSON.parse(args[0]) as boolean[];
      const enc = new BooleanEncoder();
      for (const v of arr) enc.append(v);
      console.log(toHex(enc.finish()));
      break;
    }
    case 'decode-bool': {
      const data = fromHex(args[0]);
      const dec = new BooleanDecoder(data);
      console.log(JSON.stringify(dec.readAll()));
      break;
    }
    case 'serialize-columns': {
      const cols = JSON.parse(args[0]) as ColumnData[];
      console.log(toHex(serializeColumns(cols)));
      break;
    }
    case 'deserialize-columns': {
      const data = fromHex(args[0]);
      console.log(JSON.stringify(deserializeColumns(data)));
      break;
    }
    default:
      console.error(`Unknown command: ${command}`);
      process.exit(1);
  }
} catch (e: unknown) {
  const msg = e instanceof Error ? e.message : String(e);
  console.error(`Error: ${msg}`);
  process.exit(1);
}
'''

# Write all corrected files
write_file('/app/src/leb128.ts', leb128_ts)
write_file('/app/src/rle.ts', rle_ts)
write_file('/app/src/delta.ts', delta_ts)
write_file('/app/src/boolean.ts', boolean_ts)
write_file('/app/src/columns.ts', columns_ts)
write_file('/app/src/cli.ts', cli_ts)

print("All fixes and implementations applied successfully.")

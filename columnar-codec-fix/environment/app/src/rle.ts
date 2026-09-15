
import { encodeSLEB128, decodeSLEB128, encodeULEB128, decodeULEB128 } from './leb128';

enum RleState {
  Empty,
  InitialNullRun,
  NullRun,
  LoneVal,
  Run,
  LiteralRun,
}

/**
 * Run-length encoder for sequences of values that may include null.
 * When signed=true, values are encoded as signed LEB128; otherwise unsigned LEB128.
 */
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
        // All nulls or empty: write nothing
        break;
      case RleState.NullRun:
        this.flushNullRun(this.count);
        break;
      case RleState.LoneVal:
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

/**
 * Run-length decoder for sequences of values that may include null.
 * Reverses the encoding produced by RleEncoder.
 */
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

  /**
   * Read the next value from the RLE stream.
   * Returns undefined when no more data is available.
   */
  next(): (number | null) | undefined {
    throw new Error("Not implemented");
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

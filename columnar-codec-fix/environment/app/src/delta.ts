
import { RleEncoder, RleDecoder } from './rle';

/**
 * Delta encoder: converts absolute values to a differential
 * representation, then applies signed RLE compression.
 * Null values pass through without affecting the running state.
 */
export class DeltaEncoder {
  append(value: number | null): void {
    throw new Error("Not implemented");
  }

  finish(): number[] {
    throw new Error("Not implemented");
  }
}

/**
 * Delta decoder: reverses the delta encoding to reconstruct
 * absolute values from a compressed byte stream.
 * Null values pass through without affecting the running state.
 */
export class DeltaDecoder {
  constructor(data: Uint8Array) {
    throw new Error("Not implemented");
  }

  next(): (number | null) | undefined {
    throw new Error("Not implemented");
  }

  readAll(): (number | null)[] {
    throw new Error("Not implemented");
  }
}

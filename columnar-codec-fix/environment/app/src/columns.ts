
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

/**
 * Serialize multiple typed columns into a single byte stream
 * according to the columnar wire format.
 */
export function serializeColumns(columns: ColumnData[]): number[] {
  throw new Error("Not implemented");
}

/**
 * Deserialize a byte stream back into typed columns.
 */
export function deserializeColumns(data: Uint8Array): ColumnData[] {
  throw new Error("Not implemented");
}

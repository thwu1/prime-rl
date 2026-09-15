
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
  const bytes = trimmed.split(/\s+/).map(s => parseInt(s, 16));
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

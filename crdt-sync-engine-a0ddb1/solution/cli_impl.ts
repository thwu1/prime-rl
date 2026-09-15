
import { Encoder, Decoder } from './encoding';
import { encodeStateVector, decodeStateVector } from './update';
import { Doc } from './document';
import { syncPair, syncAll } from './sync';

export function runCli(args: string[]): string {
  const cmd = args[0];
  const arg = args.slice(1).join(' ');

  switch (cmd) {
    case 'encode-sv': {
      const obj = JSON.parse(arg);
      const sv = new Map<number, number>();
      for (const [k, v] of Object.entries(obj)) {
        sv.set(Number(k), v as number);
      }
      const bytes = encodeStateVector(sv);
      return Buffer.from(bytes).toString('hex');
    }
    case 'decode-sv': {
      const bytes = new Uint8Array(Buffer.from(arg.trim(), 'hex'));
      const sv = decodeStateVector(bytes);
      const obj: { [k: string]: number } = {};
      for (const [k, v] of sv) {
        obj[String(k)] = v;
      }
      return JSON.stringify(obj);
    }
    case 'roundtrip-any': {
      const val = JSON.parse(arg);
      const enc = new Encoder();
      enc.writeAny(val);
      const dec = new Decoder(enc.toUint8Array());
      const result = dec.readAny();
      return JSON.stringify(result);
    }
    case 'simulate': {
      const scenario = JSON.parse(arg);
      const docs = new Map<number, Doc>();
      for (const id of scenario.docs) {
        docs.set(id, new Doc(id));
      }
      for (const op of scenario.ops) {
        if (op.op === 'sync') {
          syncAll([...docs.values()]);
        } else if (op.op === 'sync_pair') {
          const [a, b] = op.docs;
          syncPair(docs.get(a)!, docs.get(b)!);
        } else if (op.op === 'set') {
          docs.get(op.doc)!.mapSet(op.map, op.key, op.value);
        } else if (op.op === 'delete') {
          docs.get(op.doc)!.mapDelete(op.map, op.key);
        }
      }
      const mapNames = new Set<string>();
      for (const op of scenario.ops) {
        if (op.map) mapNames.add(op.map);
      }
      const result: { [docId: string]: { [mapName: string]: { [key: string]: any } } } = {};
      for (const [id, doc] of docs) {
        const docState: { [mapName: string]: { [key: string]: any } } = {};
        for (const name of mapNames) {
          const entries: { [key: string]: any } = {};
          for (const [k, v] of doc.mapEntries(name)) {
            entries[k] = v;
          }
          docState[name] = entries;
        }
        result[String(id)] = docState;
      }
      return JSON.stringify(result);
    }
    default:
      throw new Error(`Unknown command: ${cmd}`);
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  console.log(runCli(args));
}


import * as fs from 'fs';
import { parseUpdate } from './parse-update';
import { writeUpdate } from './write-update';
import { mergeUpdates } from './merge-updates';
import { computeStateVector, decodeStateVector, diffUpdate } from './state-vector';

function readBinaryFile(path: string): Uint8Array {
  const content = fs.readFileSync(path, 'utf-8');
  return new Uint8Array(Buffer.from(content, 'utf-8'));
}

function writeBinaryFile(path: string, data: Uint8Array): void {
  fs.writeFileSync(path, Buffer.from(data));
}

const args = process.argv.slice(2);
const command = args[0];

try {
  switch (command) {
    case 'inspect': {
      const file = args[1];
      if (!file) { console.error('Usage: cli inspect <file>'); process.exit(1); }
      const data = readBinaryFile(file);
      const update = parseUpdate(data);
      const clients: any = {};
      const deleteSet: any = {};
      for (const [cid, structs] of update.clients) {
        clients[String(cid)] = structs;
      }
      for (const [cid, ranges] of update.deleteSet) {
        deleteSet[String(cid)] = ranges;
      }
      console.log(JSON.stringify({ clients, deleteSet }, null, 2));
      break;
    }
    case 'merge': {
      const outIdx = args.indexOf('-o');
      if (outIdx === -1 || outIdx + 1 >= args.length) {
        console.error('Usage: cli merge <file1> [file2...] -o <outfile>');
        process.exit(1);
      }
      const outFile = args[outIdx + 1];
      const inputFiles = args.slice(1, outIdx);
      const inputs = inputFiles.map(f => readBinaryFile(f));
      const merged = mergeUpdates(inputs);
      writeBinaryFile(outFile, merged);
      console.log('Merged ' + inputFiles.length + ' updates -> ' + outFile);
      break;
    }
    case 'sv': {
      const file = args[1];
      if (!file) { console.error('Usage: cli sv <file>'); process.exit(1); }
      const data = readBinaryFile(file);
      const update = parseUpdate(data);
      const sv = computeStateVector(update);
      const obj: Record<string, number> = {};
      for (const [k, v] of sv) { obj[String(k)] = v; }
      console.log(JSON.stringify(obj));
      break;
    }
    case 'diff': {
      const updateFile = args[1];
      const svFile = args[2];
      const outIdx = args.indexOf('-o');
      if (!updateFile || !svFile || outIdx === -1 || outIdx + 1 >= args.length) {
        console.error('Usage: cli diff <update-file> <sv-file> -o <outfile>');
        process.exit(1);
      }
      const outFile = args[outIdx + 1];
      const updateData = readBinaryFile(updateFile);
      const svData = readBinaryFile(svFile);
      const update = parseUpdate(updateData);
      const remoteSV = decodeStateVector(svData);
      const diffed = diffUpdate(update, remoteSV);
      writeBinaryFile(outFile, writeUpdate(diffed));
      console.log('Diff written to ' + outFile);
      break;
    }
    default:
      console.error('Unknown command: ' + command);
      console.error('Commands: inspect, merge, sv, diff');
      process.exit(1);
  }
} catch (err: any) {
  console.error('Error: ' + (err.message || String(err)));
  process.exit(1);
}

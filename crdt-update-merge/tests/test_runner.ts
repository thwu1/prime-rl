
import * as fs from 'fs';
import { execSync } from 'child_process';
import { Encoder } from './encoder';
import { Decoder } from './decoder';
import { parseUpdate } from './parse-update';
import { writeUpdate } from './write-update';
import { mergeUpdates } from './merge-updates';
import { mergeDeleteRanges } from './delete-set';
import { computeStateVector, encodeStateVector, decodeStateVector, diffUpdate } from './state-vector';
import { Update, Struct, createUpdate } from './types';

interface TestResult {
  name: string;
  passed: boolean;
  error?: string;
}

const results: TestResult[] = [];

function test(name: string, fn: () => void): void {
  try {
    fn();
    results.push({ name, passed: true });
  } catch (e: any) {
    results.push({ name, passed: false, error: e.message || String(e) });
  }
}

function assert(condition: boolean, msg: string): void {
  if (!condition) throw new Error(`Assertion failed: ${msg}`);
}

function assertEqual(a: any, b: any, msg: string): void {
  const sa = JSON.stringify(a);
  const sb = JSON.stringify(b);
  if (sa !== sb) {
    throw new Error(`${msg}: expected ${sb}, got ${sa}`);
  }
}

function makeSimpleUpdate(
  clientID: number, clock: number, length: number,
  value: string, parentKey: string = 'root'
): Update {
  const update = createUpdate();
  update.clients.set(clientID, [{
    id: { client: clientID, clock },
    length,
    origin: null,
    rightOrigin: null,
    parentKey,
    contentType: 2,
    contentValue: value,
  }]);
  return update;
}

// ===== Encoding round-trips =====

test('varuint_roundtrip', () => {
  const values = [0, 1, 63, 64, 127, 128, 255, 256, 16383, 16384, 1000000, 0x7FFFFFFF];
  for (const v of values) {
    const enc = new Encoder();
    enc.writeVarUint(v);
    const dec = new Decoder(enc.toUint8Array());
    const result = dec.readVarUint();
    assertEqual(result, v, `VarUint roundtrip for ${v}`);
  }
});

test('varstring_roundtrip', () => {
  const strings = ['', 'hello', 'hello world', 'abc123!@#', 'a'.repeat(300)];
  for (const s of strings) {
    const enc = new Encoder();
    enc.writeVarString(s);
    const dec = new Decoder(enc.toUint8Array());
    const result = dec.readVarString();
    assertEqual(result, s, `VarString roundtrip for "${s.slice(0, 20)}..."`);
  }
});

// ===== Update parse/write =====

test('simple_update_roundtrip', () => {
  const update = makeSimpleUpdate(1, 0, 5, 'hello');
  const binary = writeUpdate(update);
  const parsed = parseUpdate(binary);
  const rewritten = writeUpdate(parsed);

  assert(parsed.clients.has(1), 'Should have client 1');
  const structs = parsed.clients.get(1)!;
  assertEqual(structs.length, 1, 'Should have 1 struct');
  assertEqual(structs[0].id.client, 1, 'Client ID');
  assertEqual(structs[0].id.clock, 0, 'Clock');
  assertEqual(structs[0].length, 5, 'Length');
  assertEqual(structs[0].contentType, 2, 'Content type should be string(2)');
  assertEqual(structs[0].contentValue, 'hello', 'Content value');
  assertEqual(Array.from(binary), Array.from(rewritten), 'Binary roundtrip should match');
});

test('update_with_origin_only', () => {
  const update = createUpdate();
  update.clients.set(1, [{
    id: { client: 1, clock: 0 },
    length: 3,
    origin: { client: 0, clock: 5 },
    rightOrigin: null,
    parentKey: 'text',
    contentType: 2,
    contentValue: 'abc',
  }]);

  const binary = writeUpdate(update);
  const parsed = parseUpdate(binary);
  const struct = parsed.clients.get(1)![0];

  assert(struct.origin !== null, 'Should have origin');
  assertEqual(struct.origin!.client, 0, 'Origin client');
  assertEqual(struct.origin!.clock, 5, 'Origin clock');
  assert(struct.rightOrigin === null, 'Should not have rightOrigin');
});

test('update_with_both_origins', () => {
  const update = createUpdate();
  update.clients.set(2, [{
    id: { client: 2, clock: 10 },
    length: 1,
    origin: { client: 1, clock: 3 },
    rightOrigin: { client: 1, clock: 4 },
    parentKey: 'list',
    contentType: 2,
    contentValue: 'x',
  }]);

  const binary = writeUpdate(update);
  const parsed = parseUpdate(binary);
  const struct = parsed.clients.get(2)![0];

  assert(struct.origin !== null, 'Should have origin');
  assertEqual(struct.origin!.client, 1, 'Origin client');
  assertEqual(struct.origin!.clock, 3, 'Origin clock');
  assert(struct.rightOrigin !== null, 'Should have rightOrigin');
  assertEqual(struct.rightOrigin!.client, 1, 'RightOrigin client');
  assertEqual(struct.rightOrigin!.clock, 4, 'RightOrigin clock');
});

test('update_with_right_origin_only', () => {
  const update = createUpdate();
  update.clients.set(3, [{
    id: { client: 3, clock: 0 },
    length: 2,
    origin: null,
    rightOrigin: { client: 1, clock: 0 },
    parentKey: 'doc',
    contentType: 2,
    contentValue: 'hi',
  }]);

  const binary = writeUpdate(update);
  const parsed = parseUpdate(binary);
  const struct = parsed.clients.get(3)![0];

  assert(struct.origin === null, 'Should not have origin');
  assert(struct.rightOrigin !== null, 'Should have rightOrigin');
  assertEqual(struct.rightOrigin!.client, 1, 'RightOrigin client');
  assertEqual(struct.rightOrigin!.clock, 0, 'RightOrigin clock');
});

test('multi_client_descending_order', () => {
  const update = createUpdate();
  update.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 1,
    origin: null, rightOrigin: null,
    parentKey: 'r', contentType: 2, contentValue: 'a',
  }]);
  update.clients.set(5, [{
    id: { client: 5, clock: 0 }, length: 1,
    origin: null, rightOrigin: null,
    parentKey: 'r', contentType: 2, contentValue: 'b',
  }]);
  update.clients.set(3, [{
    id: { client: 3, clock: 0 }, length: 1,
    origin: null, rightOrigin: null,
    parentKey: 'r', contentType: 2, contentValue: 'c',
  }]);

  const binary = writeUpdate(update);
  // Verify descending order by manually reading the binary
  const decoder = new Decoder(binary);
  const numClients = decoder.readVarUint();
  assertEqual(numClients, 3, 'Should have 3 clients');
  const firstClientID = decoder.readVarUint();
  assertEqual(firstClientID, 5, 'First client should be 5 (highest, descending order)');
});

test('multiple_structs_per_client', () => {
  const update = createUpdate();
  update.clients.set(1, [
    {
      id: { client: 1, clock: 0 }, length: 3,
      origin: null, rightOrigin: null,
      parentKey: 'text', contentType: 2, contentValue: 'abc',
    },
    {
      id: { client: 1, clock: 3 }, length: 2,
      origin: { client: 1, clock: 2 }, rightOrigin: null,
      parentKey: 'text', contentType: 2, contentValue: 'de',
    },
    {
      id: { client: 1, clock: 5 }, length: 1,
      origin: null, rightOrigin: null,
      parentKey: 'text', contentType: 1, contentValue: null,
    },
  ]);

  const binary = writeUpdate(update);
  const parsed = parseUpdate(binary);
  const structs = parsed.clients.get(1)!;

  assertEqual(structs.length, 3, 'Should have 3 structs');
  assertEqual(structs[0].id.clock, 0, 'First struct clock');
  assertEqual(structs[0].contentValue, 'abc', 'First struct value');
  assertEqual(structs[1].id.clock, 3, 'Second struct clock');
  assertEqual(structs[1].contentValue, 'de', 'Second struct value');
  assert(structs[1].origin !== null, 'Second struct should have origin');
  assertEqual(structs[1].origin!.client, 1, 'Second struct origin client');
  assertEqual(structs[1].origin!.clock, 2, 'Second struct origin clock');
  assertEqual(structs[2].id.clock, 5, 'Third struct clock');
  assertEqual(structs[2].contentType, 1, 'Third struct is deleted type');
});

test('delete_set_roundtrip', () => {
  const update = createUpdate();
  update.deleteSet.set(1, [
    { clock: 0, length: 3 },
    { clock: 10, length: 5 },
  ]);
  update.deleteSet.set(2, [
    { clock: 5, length: 2 },
  ]);

  const binary = writeUpdate(update);
  const parsed = parseUpdate(binary);

  assert(parsed.deleteSet.has(1), 'Has delete set for client 1');
  assert(parsed.deleteSet.has(2), 'Has delete set for client 2');
  const ranges1 = parsed.deleteSet.get(1)!;
  assertEqual(ranges1.length, 2, 'Client 1 has 2 ranges');
  assertEqual(ranges1[0], { clock: 0, length: 3 }, 'First range');
  assertEqual(ranges1[1], { clock: 10, length: 5 }, 'Second range');
});

test('gc_and_deleted_content_types', () => {
  const update = createUpdate();
  update.clients.set(1, [
    {
      id: { client: 1, clock: 0 }, length: 4,
      origin: null, rightOrigin: null,
      parentKey: 'doc', contentType: 0, contentValue: null,
    },
    {
      id: { client: 1, clock: 4 }, length: 2,
      origin: null, rightOrigin: null,
      parentKey: 'doc', contentType: 1, contentValue: null,
    },
  ]);

  const binary = writeUpdate(update);
  const parsed = parseUpdate(binary);
  const structs = parsed.clients.get(1)!;

  assertEqual(structs[0].contentType, 0, 'First struct is GC');
  assertEqual(structs[0].length, 4, 'GC length');
  assertEqual(structs[1].contentType, 1, 'Second struct is Deleted');
  assertEqual(structs[1].length, 2, 'Deleted length');
});

// ===== Delete set merging =====

test('delete_range_merge_overlapping', () => {
  const a = [{ clock: 0, length: 5 }];
  const b = [{ clock: 3, length: 4 }];
  const merged = mergeDeleteRanges(a, b);
  assertEqual(merged.length, 1, 'Should merge overlapping to 1 range');
  assertEqual(merged[0], { clock: 0, length: 7 }, 'Merged range [0,7)');
});

test('delete_range_merge_adjacent', () => {
  const a = [{ clock: 0, length: 3 }];
  const b = [{ clock: 3, length: 2 }];
  const merged = mergeDeleteRanges(a, b);
  assertEqual(merged.length, 1, 'Adjacent ranges should merge to 1');
  assertEqual(merged[0], { clock: 0, length: 5 }, 'Merged range [0,5)');
});

test('delete_range_merge_disjoint', () => {
  const a = [{ clock: 0, length: 2 }];
  const b = [{ clock: 5, length: 3 }];
  const merged = mergeDeleteRanges(a, b);
  assertEqual(merged.length, 2, 'Disjoint ranges should remain separate');
  assertEqual(merged[0], { clock: 0, length: 2 }, 'First range');
  assertEqual(merged[1], { clock: 5, length: 3 }, 'Second range');
});

test('delete_range_merge_complex', () => {
  const a = [{ clock: 0, length: 3 }, { clock: 10, length: 5 }];
  const b = [{ clock: 2, length: 4 }, { clock: 15, length: 2 }];
  const merged = mergeDeleteRanges(a, b);
  // [0,3) + [2,6) = [0,6); [10,15) + [15,17) = [10,17)
  assertEqual(merged.length, 2, 'Should produce 2 merged ranges');
  assertEqual(merged[0], { clock: 0, length: 6 }, 'First merged range');
  assertEqual(merged[1], { clock: 10, length: 7 }, 'Second merged range');
});

// ===== Update merging =====

test('merge_non_overlapping_clients', () => {
  const update1 = makeSimpleUpdate(1, 0, 3, 'abc');
  const update2 = makeSimpleUpdate(2, 0, 2, 'de');

  const bin1 = writeUpdate(update1);
  const bin2 = writeUpdate(update2);
  const merged = mergeUpdates([bin1, bin2]);
  const parsed = parseUpdate(merged);

  assert(parsed.clients.has(1), 'Merged has client 1');
  assert(parsed.clients.has(2), 'Merged has client 2');
  assertEqual(parsed.clients.get(1)![0].contentValue, 'abc', 'Client 1 content');
  assertEqual(parsed.clients.get(2)![0].contentValue, 'de', 'Client 2 content');
});

test('merge_same_client_sequential', () => {
  const update1 = createUpdate();
  update1.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 3,
    origin: null, rightOrigin: null,
    parentKey: 'text', contentType: 2, contentValue: 'abc',
  }]);

  const update2 = createUpdate();
  update2.clients.set(1, [{
    id: { client: 1, clock: 3 }, length: 2,
    origin: { client: 1, clock: 2 }, rightOrigin: null,
    parentKey: 'text', contentType: 2, contentValue: 'de',
  }]);

  const bin1 = writeUpdate(update1);
  const bin2 = writeUpdate(update2);
  const merged = mergeUpdates([bin1, bin2]);
  const parsed = parseUpdate(merged);

  const structs = parsed.clients.get(1)!;
  assertEqual(structs.length, 2, 'Should have 2 structs');
  assertEqual(structs[0].id.clock, 0, 'First at clock 0');
  assertEqual(structs[1].id.clock, 3, 'Second at clock 3');
});

test('merge_duplicate_structs', () => {
  const update = makeSimpleUpdate(1, 0, 3, 'abc');
  const bin = writeUpdate(update);
  const merged = mergeUpdates([bin, bin]);
  const parsed = parseUpdate(merged);

  const structs = parsed.clients.get(1)!;
  assertEqual(structs.length, 1, 'Duplicates should be deduplicated');
  assertEqual(structs[0].contentValue, 'abc', 'Content preserved');
});

test('merge_with_delete_sets', () => {
  const update1 = createUpdate();
  update1.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 5,
    origin: null, rightOrigin: null,
    parentKey: 'text', contentType: 2, contentValue: 'hello',
  }]);
  update1.deleteSet.set(1, [{ clock: 0, length: 2 }]);

  const update2 = createUpdate();
  update2.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 5,
    origin: null, rightOrigin: null,
    parentKey: 'text', contentType: 2, contentValue: 'hello',
  }]);
  update2.deleteSet.set(1, [{ clock: 2, length: 3 }]);

  const bin1 = writeUpdate(update1);
  const bin2 = writeUpdate(update2);
  const merged = mergeUpdates([bin1, bin2]);
  const parsed = parseUpdate(merged);

  const deleteRanges = parsed.deleteSet.get(1)!;
  assertEqual(deleteRanges.length, 1, 'Delete sets merged to 1 range');
  assertEqual(deleteRanges[0], { clock: 0, length: 5 }, 'Merged delete range [0,5)');
});

test('merge_three_updates', () => {
  const u1 = createUpdate();
  u1.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 2,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'ab',
  }]);

  const u2 = createUpdate();
  u2.clients.set(2, [{
    id: { client: 2, clock: 0 }, length: 3,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'cde',
  }]);

  const u3 = createUpdate();
  u3.clients.set(1, [{
    id: { client: 1, clock: 2 }, length: 1,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'f',
  }]);
  u3.clients.set(3, [{
    id: { client: 3, clock: 0 }, length: 1,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 0, contentValue: null,
  }]);

  const merged = mergeUpdates([writeUpdate(u1), writeUpdate(u2), writeUpdate(u3)]);
  const parsed = parseUpdate(merged);

  assert(parsed.clients.has(1), 'Has client 1');
  assert(parsed.clients.has(2), 'Has client 2');
  assert(parsed.clients.has(3), 'Has client 3');
  assertEqual(parsed.clients.get(1)!.length, 2, 'Client 1 has 2 structs');
  assertEqual(parsed.clients.get(2)!.length, 1, 'Client 2 has 1 struct');
  assertEqual(parsed.clients.get(3)!.length, 1, 'Client 3 has 1 struct');
  assertEqual(parsed.clients.get(3)![0].contentType, 0, 'Client 3 is GC');
});

test('merge_idempotent', () => {
  const update = createUpdate();
  update.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 3,
    origin: null, rightOrigin: null,
    parentKey: 'root', contentType: 2, contentValue: 'xyz',
  }]);
  update.deleteSet.set(1, [{ clock: 0, length: 1 }]);

  const bin = writeUpdate(update);
  const merged = mergeUpdates([bin, bin, bin]);
  const parsed = parseUpdate(merged);

  assertEqual(parsed.clients.get(1)!.length, 1, 'Idempotent: 1 struct');
  assertEqual(parsed.clients.get(1)![0].contentValue, 'xyz', 'Content preserved');
  assertEqual(parsed.deleteSet.get(1)!.length, 1, 'Idempotent: 1 delete range');
  assertEqual(parsed.deleteSet.get(1)![0], { clock: 0, length: 1 }, 'Delete preserved');
});

test('merge_empty_updates', () => {
  const empty = writeUpdate(createUpdate());
  const merged = mergeUpdates([empty, empty]);
  const parsed = parseUpdate(merged);
  assertEqual(parsed.clients.size, 0, 'No clients in merged empty');
  assertEqual(parsed.deleteSet.size, 0, 'No delete sets in merged empty');
});

test('merge_preserves_all_content_types', () => {
  const u1 = createUpdate();
  u1.clients.set(1, [
    { id: { client: 1, clock: 0 }, length: 2, origin: null, rightOrigin: null,
      parentKey: 'doc', contentType: 0, contentValue: null },
    { id: { client: 1, clock: 2 }, length: 3, origin: null, rightOrigin: null,
      parentKey: 'doc', contentType: 1, contentValue: null },
  ]);

  const u2 = createUpdate();
  u2.clients.set(1, [{
    id: { client: 1, clock: 5 }, length: 4, origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'test',
  }]);

  const merged = mergeUpdates([writeUpdate(u1), writeUpdate(u2)]);
  const parsed = parseUpdate(merged);
  const structs = parsed.clients.get(1)!;

  assertEqual(structs.length, 3, 'Should have 3 structs');
  assertEqual(structs[0].contentType, 0, 'First is GC');
  assertEqual(structs[0].length, 2, 'GC length');
  assertEqual(structs[1].contentType, 1, 'Second is Deleted');
  assertEqual(structs[2].contentType, 2, 'Third is String');
  assertEqual(structs[2].contentValue, 'test', 'String value');
});

// ===== State vector tests =====

test('sv_single_client', () => {
  const update = makeSimpleUpdate(1, 0, 5, 'hello');
  const sv = computeStateVector(update);
  assertEqual(sv.get(1), 5, 'SV for client 1 should be 5 (next expected clock)');
});

test('sv_multi_client', () => {
  const update = createUpdate();
  update.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 3,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'abc',
  }]);
  update.clients.set(2, [{
    id: { client: 2, clock: 0 }, length: 7,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'defghij',
  }]);
  const sv = computeStateVector(update);
  assertEqual(sv.get(1), 3, 'SV for client 1');
  assertEqual(sv.get(2), 7, 'SV for client 2');
});

test('sv_encode_decode_roundtrip', () => {
  const sv = new Map<number, number>();
  sv.set(1, 5);
  sv.set(42, 100);
  sv.set(300, 0);
  const encoded = encodeStateVector(sv);
  const decoded = decodeStateVector(encoded);
  assertEqual(decoded.get(1), 5, 'Client 1 clock');
  assertEqual(decoded.get(42), 100, 'Client 42 clock');
  assertEqual(decoded.get(300), 0, 'Client 300 clock');
  assertEqual(decoded.size, 3, 'SV size');
});

test('diff_missing_client', () => {
  const update = createUpdate();
  update.clients.set(1, [{
    id: { client: 1, clock: 0 }, length: 3,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'abc',
  }]);
  update.clients.set(2, [{
    id: { client: 2, clock: 0 }, length: 2,
    origin: null, rightOrigin: null,
    parentKey: 'doc', contentType: 2, contentValue: 'de',
  }]);

  // Remote knows about client 1 (up to clock 3) but not client 2
  const remoteSV = new Map<number, number>();
  remoteSV.set(1, 3);

  const diff = diffUpdate(update, remoteSV);
  assert(!diff.clients.has(1), 'Client 1 fully known, should not be in diff');
  assert(diff.clients.has(2), 'Client 2 unknown, should be in diff');
});

test('diff_partial_overlap', () => {
  // A struct that spans the boundary: starts at clock 2, length 5, covers [2,7)
  // Remote has clock 4 (knows [0,4)), so clocks [4,7) are missing
  // The struct should be included since its range extends past remoteClock
  const update = createUpdate();
  update.clients.set(1, [{
    id: { client: 1, clock: 2 }, length: 5,
    origin: null, rightOrigin: null,
    parentKey: 'text', contentType: 2, contentValue: 'abcde',
  }]);

  const remoteSV = new Map<number, number>();
  remoteSV.set(1, 4);

  const diff = diffUpdate(update, remoteSV);
  assert(diff.clients.has(1), 'Struct at [2,7) extends past remote clock 4, must be included');
  assertEqual(diff.clients.get(1)!.length, 1, 'Should have 1 struct');
});

// ===== CLI integration tests =====

test('cli_inspect', () => {
  // Use clientID=200 to produce varint bytes > 0x7F, exercising binary I/O
  const update = makeSimpleUpdate(200, 0, 3, 'xyz');
  const binary = writeUpdate(update);
  fs.writeFileSync('/tmp/test_inspect.bin', Buffer.from(binary));

  const output = execSync('node /app/dist/cli.js inspect /tmp/test_inspect.bin', { encoding: 'utf-8' });
  const result = JSON.parse(output.trim());
  assert(result.clients['200'] !== undefined, 'Should have client 200');
  assertEqual(result.clients['200'].length, 1, 'Should have 1 struct for client 200');
  assertEqual(result.clients['200'][0].contentValue, 'xyz', 'Content should be xyz');
});

test('cli_merge_files', () => {
  const u1 = makeSimpleUpdate(150, 0, 2, 'ab');
  const u2 = makeSimpleUpdate(250, 0, 3, 'cde');
  fs.writeFileSync('/tmp/test_merge1.bin', Buffer.from(writeUpdate(u1)));
  fs.writeFileSync('/tmp/test_merge2.bin', Buffer.from(writeUpdate(u2)));

  execSync('node /app/dist/cli.js merge /tmp/test_merge1.bin /tmp/test_merge2.bin -o /tmp/test_merged.bin');
  const mergedBuf = fs.readFileSync('/tmp/test_merged.bin');
  const parsed = parseUpdate(new Uint8Array(mergedBuf));
  assert(parsed.clients.has(150), 'Merged should have client 150');
  assert(parsed.clients.has(250), 'Merged should have client 250');
});

test('cli_state_vector', () => {
  const update = makeSimpleUpdate(180, 0, 7, 'testing');
  fs.writeFileSync('/tmp/test_sv_cli.bin', Buffer.from(writeUpdate(update)));

  const output = execSync('node /app/dist/cli.js sv /tmp/test_sv_cli.bin', { encoding: 'utf-8' });
  const sv = JSON.parse(output.trim());
  assertEqual(sv['180'], 7, 'State vector for client 180 should be 7');
});

test('cli_diff', () => {
  const update = createUpdate();
  update.clients.set(500, [{
    id: { client: 500, clock: 0 }, length: 5,
    origin: null, rightOrigin: null,
    parentKey: 'text', contentType: 2, contentValue: 'hello',
  }]);
  update.clients.set(600, [{
    id: { client: 600, clock: 0 }, length: 3,
    origin: null, rightOrigin: null,
    parentKey: 'text', contentType: 2, contentValue: 'wld',
  }]);

  const sv = new Map<number, number>();
  sv.set(500, 5); // remote knows all of client 500

  fs.writeFileSync('/tmp/test_diff_update.bin', Buffer.from(writeUpdate(update)));
  fs.writeFileSync('/tmp/test_diff_sv.bin', Buffer.from(encodeStateVector(sv)));

  execSync('node /app/dist/cli.js diff /tmp/test_diff_update.bin /tmp/test_diff_sv.bin -o /tmp/test_diff_out.bin');
  const diffBuf = fs.readFileSync('/tmp/test_diff_out.bin');
  const diffed = parseUpdate(new Uint8Array(diffBuf));

  assert(!diffed.clients.has(500), 'Client 500 fully known, not in diff');
  assert(diffed.clients.has(600), 'Client 600 missing, should be in diff');
});

// ===== Output results =====
console.log(JSON.stringify(results, null, 2));
process.exit(results.every(r => r.passed) ? 0 : 1);

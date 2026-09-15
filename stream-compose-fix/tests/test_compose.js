
'use strict';

const assert = require('assert');
const {
  Transform,
  PassThrough,
  Writable,
  Readable,
  Duplex,
  finished,
} = require('stream');

const { composeStreams } = require('/app/dist/compose');

const tests = {};

// ---------------------------------------------------------------------------
// Test 1: Simple two-transform composition
// ---------------------------------------------------------------------------
tests.simple_composition = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('simple_composition timed out')),
      5000,
    );

    let result = '';
    const t1 = new Transform({
      transform(chunk, _enc, cb) {
        cb(null, chunk.toString().toUpperCase());
      },
    });
    const t2 = new Transform({
      transform(chunk, _enc, cb) {
        cb(null, chunk.toString() + '!');
      },
    });

    const composed = composeStreams(t1, t2);
    composed.on('data', (chunk) => {
      result += chunk.toString();
    });
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(result, 'HELLO!WORLD!');
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write('hello');
    composed.write('world');
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 2: Object mode propagation
// ---------------------------------------------------------------------------
tests.object_mode = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('object_mode timed out')),
      5000,
    );

    const parser = new Transform({
      readableObjectMode: true,
      writableObjectMode: false,
      transform(chunk, _enc, cb) {
        cb(null, { value: chunk.toString() });
      },
    });

    const mapper = new Transform({
      objectMode: true,
      transform(obj, _enc, cb) {
        cb(null, { ...obj, mapped: true });
      },
    });

    const composed = composeStreams(parser, mapper);

    try {
      assert.strictEqual(
        composed.writableObjectMode,
        false,
        'writableObjectMode should be false (inherited from head)',
      );
      assert.strictEqual(
        composed.readableObjectMode,
        true,
        'readableObjectMode should be true (inherited from tail)',
      );
    } catch (e) {
      clearTimeout(timeout);
      reject(e);
      return;
    }

    const results = [];
    composed.on('data', (chunk) => {
      results.push(chunk);
    });
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(results.length, 1);
        assert.deepStrictEqual(results[0], { value: 'test', mapped: true });
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write(Buffer.from('test'));
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 3: Backpressure (drain handling)
// ---------------------------------------------------------------------------
tests.backpressure = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () =>
        reject(
          new Error(
            'backpressure timed out — drain callback likely not invoked',
          ),
        ),
      5000,
    );

    // A slow transform that delays processing
    const slow = new Transform({
      highWaterMark: 1,
      transform(chunk, _enc, cb) {
        setTimeout(() => cb(null, chunk), 10);
      },
    });

    const pass = new PassThrough({ highWaterMark: 1 });
    const composed = composeStreams(pass, slow);

    const chunks = [];
    composed.on('data', (chunk) => {
      chunks.push(chunk.toString());
    });
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(
          chunks.length,
          5,
          `Expected 5 chunks, got ${chunks.length}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    for (let i = 0; i < 5; i++) {
      composed.write(`chunk${i}`);
    }
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 4: Error propagation from middle stage
// ---------------------------------------------------------------------------
tests.error_propagation = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () =>
        reject(
          new Error(
            'error_propagation timed out — error likely not propagated to composed stream',
          ),
        ),
      5000,
    );

    const expectedError = new Error('deliberate middle stage error');

    const t1 = new PassThrough();
    const t2 = new Transform({
      transform(_chunk, _enc, cb) {
        cb(expectedError);
      },
    });
    const t3 = new PassThrough();

    const composed = composeStreams(t1, t2, t3);

    composed.on('error', (err) => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(err.message, expectedError.message);
        resolve();
      } catch (e) {
        reject(e);
      }
    });

    composed.on('end', () => {
      clearTimeout(timeout);
      reject(new Error('Should not have ended normally — expected an error'));
    });

    composed.write('trigger error');
  });

// ---------------------------------------------------------------------------
// Test 5: End forwarding (composed stream emits 'end')
// ---------------------------------------------------------------------------
tests.end_forwarding = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () =>
        reject(
          new Error(
            'end_forwarding timed out — end event never fired on composed stream',
          ),
        ),
      5000,
    );

    const t1 = new PassThrough();
    const t2 = new Transform({
      transform(chunk, _enc, cb) {
        cb(null, chunk);
      },
    });

    const composed = composeStreams(t1, t2);

    composed.on('data', () => {}); // consume data to enable flowing mode
    composed.on('end', () => {
      clearTimeout(timeout);
      resolve();
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write('data');
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 6: _final waits for pipeline to drain
// ---------------------------------------------------------------------------
tests.final_waits = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('final_waits timed out')),
      5000,
    );

    const events = [];

    // Slow transform: 50ms per chunk
    const slow = new Transform({
      transform(chunk, _enc, cb) {
        setTimeout(() => {
          events.push('transform');
          cb(null, chunk);
        }, 50);
      },
    });

    const pass = new PassThrough();
    const composed = composeStreams(slow, pass);

    composed.on('data', () => {
      events.push('data');
    });
    composed.on('finish', () => {
      clearTimeout(timeout);
      events.push('finish');
      try {
        // With correct _final deferral, all data events precede finish
        const dataCount = events.filter((e) => e === 'data').length;
        assert(
          dataCount >= 2,
          `Expected at least 2 data events before finish, got ${dataCount}. Events: ${events.join(', ')}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write('a');
    composed.write('b');
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 7: Destroy cleanup
// ---------------------------------------------------------------------------
tests.destroy_cleanup = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('destroy_cleanup timed out')),
      5000,
    );

    const t1 = new PassThrough();
    const t2 = new PassThrough();
    const t3 = new PassThrough();

    const composed = composeStreams(t1, t2, t3);

    // Suppress unhandled error
    composed.on('error', () => {});
    t1.on('error', () => {});
    t2.on('error', () => {});
    t3.on('error', () => {});

    composed.destroy(new Error('test destroy'));

    setTimeout(() => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(
          t1.destroyed,
          true,
          'head stream should be destroyed',
        );
        assert.strictEqual(
          t2.destroyed,
          true,
          'middle stream should be destroyed',
        );
        assert.strictEqual(
          t3.destroyed,
          true,
          'tail stream should be destroyed',
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    }, 200);
  });

// ---------------------------------------------------------------------------
// Test 8: Three-stage composition with data verification
// ---------------------------------------------------------------------------
tests.three_stage = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('three_stage timed out')),
      5000,
    );

    const upper = new Transform({
      transform(chunk, _enc, cb) {
        cb(null, chunk.toString().toUpperCase());
      },
    });
    const exclaim = new Transform({
      transform(chunk, _enc, cb) {
        cb(null, chunk.toString() + '!');
      },
    });
    const wrap = new Transform({
      transform(chunk, _enc, cb) {
        cb(null, '[' + chunk.toString() + ']');
      },
    });

    const composed = composeStreams(upper, exclaim, wrap);

    let result = '';
    composed.on('data', (chunk) => {
      result += chunk.toString();
    });
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(result, '[HELLO!][WORLD!]');
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write('hello');
    composed.write('world');
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 9: Async generator as a pipeline stage
// ---------------------------------------------------------------------------
tests.async_generator_stage = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('async_generator_stage timed out')),
      5000,
    );

    // Head emits objects via readableObjectMode
    const head = new Transform({
      readableObjectMode: true,
      transform(chunk, _enc, cb) {
        cb(null, { text: chunk.toString() });
      },
    });

    // Generator stage transforms objects
    const gen = async function* (source) {
      for await (const obj of source) {
        yield { ...obj, transformed: true };
      }
    };

    const composed = composeStreams(head, gen);

    const results = [];
    composed.on('data', (chunk) => {
      results.push(chunk);
    });
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(results.length, 2);
        assert.deepStrictEqual(results[0], {
          text: 'hello',
          transformed: true,
        });
        assert.deepStrictEqual(results[1], {
          text: 'world',
          transformed: true,
        });
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write(Buffer.from('hello'));
    composed.write(Buffer.from('world'));
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 10: Generator error propagation
// ---------------------------------------------------------------------------
tests.generator_error = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () =>
        reject(
          new Error(
            'generator_error timed out — error likely not propagated',
          ),
        ),
      5000,
    );

    const t1 = new PassThrough();
    const failing = async function* (source) {
      for await (const _chunk of source) {
        throw new Error('generator failure');
      }
    };

    const composed = composeStreams(t1, failing);

    composed.on('error', (err) => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(err.message, 'generator failure');
        resolve();
      } catch (e) {
        reject(e);
      }
    });

    composed.on('end', () => {
      clearTimeout(timeout);
      reject(new Error('Should not end normally — expected error'));
    });

    composed.write('trigger');
  });

// ---------------------------------------------------------------------------
// Test 11: Mixed pipeline (Transform + generator + Transform)
// ---------------------------------------------------------------------------
tests.mixed_pipeline = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('mixed_pipeline timed out')),
      8000,
    );

    // Stage 1: parse string input into objects
    const parser = new Transform({
      readableObjectMode: true,
      transform(chunk, _enc, cb) {
        cb(null, { raw: chunk.toString() });
      },
    });

    // Stage 2: async generator adds fields
    const augment = async function* (source) {
      let seq = 0;
      for await (const obj of source) {
        yield { ...obj, seq: seq++, augmented: true };
      }
    };

    // Stage 3: serialize back to newline-delimited JSON
    const serializer = new Transform({
      writableObjectMode: true,
      transform(obj, _enc, cb) {
        cb(null, JSON.stringify(obj) + '\n');
      },
    });

    const composed = composeStreams(parser, augment, serializer);

    let output = '';
    composed.on('data', (chunk) => {
      output += chunk.toString();
    });
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        const lines = output
          .trim()
          .split('\n')
          .map((l) => JSON.parse(l));
        assert.strictEqual(lines.length, 2);
        assert.deepStrictEqual(lines[0], {
          raw: 'foo',
          seq: 0,
          augmented: true,
        });
        assert.deepStrictEqual(lines[1], {
          raw: 'bar',
          seq: 1,
          augmented: true,
        });
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write(Buffer.from('foo'));
    composed.write(Buffer.from('bar'));
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 12: HighWaterMark inheritance
// ---------------------------------------------------------------------------
tests.hwm_inheritance = () =>
  new Promise((resolve, reject) => {
    const head = new Transform({
      highWaterMark: 42,
      transform(chunk, _enc, cb) {
        cb(null, chunk);
      },
    });

    const tail = new Transform({
      readableHighWaterMark: 99,
      writableHighWaterMark: 55,
      transform(chunk, _enc, cb) {
        cb(null, chunk);
      },
    });

    const composed = composeStreams(head, tail);

    try {
      assert.strictEqual(
        composed.writableHighWaterMark,
        42,
        `writableHighWaterMark should be 42 (from head), got ${composed.writableHighWaterMark}`,
      );
      assert.strictEqual(
        composed.readableHighWaterMark,
        99,
        `readableHighWaterMark should be 99 (from tail), got ${composed.readableHighWaterMark}`,
      );
      resolve();
    } catch (e) {
      reject(e);
    }
  });

// ---------------------------------------------------------------------------
// Test 13: Batch operator — full batches
// ---------------------------------------------------------------------------
tests.batch_full = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('batch_full timed out')),
      5000,
    );
    const { batch } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    const batcher = batch(3);
    source.pipe(batcher);

    const results = [];
    batcher.on('data', (chunk) => results.push(chunk));
    batcher.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(
          results.length,
          2,
          `Expected 2 batches, got ${results.length}: ${JSON.stringify(results)}`,
        );
        assert.deepStrictEqual(results[0], [1, 2, 3]);
        assert.deepStrictEqual(results[1], [4, 5, 6]);
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    batcher.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    for (let i = 1; i <= 6; i++) source.write(i);
    source.end();
  });

// ---------------------------------------------------------------------------
// Test 14: Batch operator — partial flush on end
// ---------------------------------------------------------------------------
tests.batch_partial_flush = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('batch_partial_flush timed out')),
      5000,
    );
    const { batch } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    const batcher = batch(3);
    source.pipe(batcher);

    const results = [];
    batcher.on('data', (chunk) => results.push(chunk));
    batcher.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(
          results.length,
          2,
          `Expected 2 batches (one full + one partial), got ${results.length}: ${JSON.stringify(results)}`,
        );
        assert.deepStrictEqual(results[0], [1, 2, 3]);
        assert.deepStrictEqual(
          results[1],
          [4, 5],
          `Partial batch should contain remaining items [4, 5]`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    batcher.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    for (let i = 1; i <= 5; i++) source.write(i);
    source.end();
  });

// ---------------------------------------------------------------------------
// Test 15: Scan operator — running accumulation via composeStreams
// ---------------------------------------------------------------------------
tests.scan_accumulation = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('scan_accumulation timed out')),
      5000,
    );
    const { scan } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    const scanner = scan((acc, val) => acc + val, 0);
    const composed = composeStreams(source, scanner);

    const results = [];
    composed.on('data', (chunk) => results.push(chunk));
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.deepStrictEqual(
          results,
          [1, 3, 6, 10],
          `Expected running sums [1,3,6,10], got ${JSON.stringify(results)}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write(1);
    composed.write(2);
    composed.write(3);
    composed.write(4);
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 16: splitLines — basic splitting
// ---------------------------------------------------------------------------
tests.split_lines_basic = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('split_lines_basic timed out')),
      5000,
    );
    const { splitLines } = require('/app/dist/operators');

    const splitter = splitLines();

    const results = [];
    splitter.on('data', (chunk) => {
      results.push(chunk);
    });
    splitter.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(results.length, 2, `Expected 2 lines, got ${results.length}`);
        for (const r of results) {
          assert.strictEqual(
            typeof r,
            'string',
            `Expected string output from readableObjectMode, got ${typeof r} (${Object.prototype.toString.call(r)})`,
          );
        }
        assert.strictEqual(results[0], 'hello');
        assert.strictEqual(results[1], 'world');
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    splitter.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    splitter.write(Buffer.from('hello\nworld\n'));
    splitter.end();
  });

// ---------------------------------------------------------------------------
// Test 17: splitLines — cross-chunk boundary assembly + trailing flush
// ---------------------------------------------------------------------------
tests.split_lines_boundary = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('split_lines_boundary timed out')),
      5000,
    );
    const { splitLines } = require('/app/dist/operators');

    const splitter = splitLines();

    const results = [];
    splitter.on('data', (chunk) => {
      results.push(typeof chunk === 'string' ? chunk : chunk.toString());
    });
    splitter.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.deepStrictEqual(
          results,
          ['hello', 'world', 'trailing'],
          `Expected ['hello','world','trailing'], got ${JSON.stringify(results)}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    splitter.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    // Write in fragments that split across line boundaries
    splitter.write(Buffer.from('hel'));
    splitter.write(Buffer.from('lo\nwor'));
    splitter.write(Buffer.from('ld\ntrailing'));
    splitter.end();
  });

// ---------------------------------------------------------------------------
// Test 18: Integration — splitLines → batch(2) → scan through composeStreams
// ---------------------------------------------------------------------------
tests.composed_pipeline = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('composed_pipeline timed out')),
      8000,
    );
    const { splitLines, batch, scan } = require('/app/dist/operators');

    // splitLines emits: "a", "b", "c", "d", "e"
    // batch(2) emits: ["a","b"], ["c","d"], ["e"] (partial flush)
    // scan counts array lengths: 2, 4, 5
    const composed = composeStreams(
      splitLines(),
      batch(2),
      scan((acc, arr) => acc + arr.length, 0),
    );

    const results = [];
    composed.on('data', (chunk) => results.push(chunk));
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.deepStrictEqual(
          results,
          [2, 4, 5],
          `Expected [2,4,5] from splitLines→batch(2)→scan(sumLen), got ${JSON.stringify(results)}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write(Buffer.from('a\nb\nc\nd\ne\n'));
    composed.end();
  });

// ---------------------------------------------------------------------------
// Test 19: flatMap — expand each item into multiple outputs
// ---------------------------------------------------------------------------
tests.flatmap_expand = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('flatmap_expand timed out')),
      5000,
    );
    const { flatMap } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    const mapper = flatMap(async function* (n) {
      for (let i = 0; i < n; i++) {
        yield `${n}_${i}`;
      }
    });
    source.pipe(mapper);

    const results = [];
    mapper.on('data', (chunk) => results.push(chunk));
    mapper.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.deepStrictEqual(
          results,
          ['1_0', '2_0', '2_1', '3_0', '3_1', '3_2'],
          `Expected expand output ['1_0','2_0','2_1','3_0','3_1','3_2'], got ${JSON.stringify(results)}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    mapper.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    source.write(1);
    source.write(2);
    source.write(3);
    source.end();
  });

// ---------------------------------------------------------------------------
// Test 20: flatMap — sequential ordering with delayed yields
// ---------------------------------------------------------------------------
tests.flatmap_ordering = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('flatmap_ordering timed out')),
      8000,
    );
    const { flatMap } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    // Each input produces two items with a delay between them.
    // Correct sequential processing yields: a1, a2, b1, b2
    // Broken concurrent processing would yield: a1, b1, a2, b2
    const mapper = flatMap(async function* (s) {
      yield s + '1';
      await new Promise((r) => setTimeout(r, 40));
      yield s + '2';
    });
    source.pipe(mapper);

    const results = [];
    mapper.on('data', (chunk) => results.push(chunk));
    mapper.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.deepStrictEqual(
          results,
          ['a1', 'a2', 'b1', 'b2'],
          `Expected sequential [a1,a2,b1,b2], got ${JSON.stringify(results)} (likely concurrent interleaving)`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    mapper.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    source.write('a');
    source.write('b');
    source.end();
  });

// ---------------------------------------------------------------------------
// Test 21: flatMap — error in async iterable propagates
// ---------------------------------------------------------------------------
tests.flatmap_error = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () =>
        reject(
          new Error(
            'flatmap_error timed out — error likely not propagated from async iterable',
          ),
        ),
      5000,
    );
    const { flatMap } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    const mapper = flatMap(async function* (_item) {
      yield 'ok_item';
      throw new Error('flatmap deliberate error');
    });
    source.pipe(mapper);

    mapper.on('error', (err) => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(err.message, 'flatmap deliberate error');
        resolve();
      } catch (e) {
        reject(e);
      }
    });

    mapper.on('end', () => {
      clearTimeout(timeout);
      reject(new Error('Should not have ended normally — expected an error'));
    });

    source.write('trigger');
  });

// ---------------------------------------------------------------------------
// Test 22: deduplicate — basic deduplication within window
// ---------------------------------------------------------------------------
tests.deduplicate_basic = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('deduplicate_basic timed out')),
      5000,
    );
    const { deduplicate } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    const dedup = deduplicate((item) => item.id, 10);
    source.pipe(dedup);

    const results = [];
    dedup.on('data', (chunk) => results.push(chunk));
    dedup.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.deepStrictEqual(
          results,
          [
            { id: 'a', val: 1 },
            { id: 'b', val: 2 },
            { id: 'c', val: 4 },
          ],
          `Expected 3 unique items, got ${JSON.stringify(results)}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    dedup.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    source.write({ id: 'a', val: 1 });
    source.write({ id: 'b', val: 2 });
    source.write({ id: 'a', val: 3 }); // duplicate key
    source.write({ id: 'c', val: 4 });
    source.write({ id: 'b', val: 5 }); // duplicate key
    source.end();
  });

// ---------------------------------------------------------------------------
// Test 23: deduplicate — window eviction allows re-entry
// ---------------------------------------------------------------------------
tests.deduplicate_window = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('deduplicate_window timed out')),
      5000,
    );
    const { deduplicate } = require('/app/dist/operators');

    const source = new PassThrough({ objectMode: true });
    // Window size 2: only the last 2 unique keys are tracked
    const dedup = deduplicate((item) => item.k, 2);
    source.pipe(dedup);

    const results = [];
    dedup.on('data', (chunk) => results.push(chunk));
    dedup.on('end', () => {
      clearTimeout(timeout);
      try {
        // Step trace with windowSize=2:
        //   {k:'x'} → emit, window=[x]
        //   {k:'y'} → emit, window=[x,y]
        //   {k:'z'} → emit, window=[y,z]  (x evicted)
        //   {k:'x'} → emit (x not in window), window=[z,x]  (y evicted)
        //   {k:'y'} → emit (y not in window), window=[x,y]  (z evicted)
        //   {k:'x'} → skip (x still in window)
        assert.deepStrictEqual(
          results,
          [
            { k: 'x' },
            { k: 'y' },
            { k: 'z' },
            { k: 'x' },
            { k: 'y' },
          ],
          `Expected 5 items with window eviction, got ${JSON.stringify(results)}`,
        );
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    dedup.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    source.write({ k: 'x' });
    source.write({ k: 'y' });
    source.write({ k: 'z' });
    source.write({ k: 'x' });
    source.write({ k: 'y' });
    source.write({ k: 'x' }); // still in window → filtered
    source.end();
  });

// ---------------------------------------------------------------------------
// Test 24: Advanced pipeline — flatMap → batch through composeStreams
// ---------------------------------------------------------------------------
tests.advanced_pipeline = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('advanced_pipeline timed out')),
      8000,
    );
    const { flatMap, batch } = require('/app/dist/operators');

    // Pipeline via composeStreams:
    //   flatMap(n → repeat n, n times) → batch(3)
    // Input: 1 → [1]; 2 → [2,2]; 3 → [3,3,3]
    // flatMap output: [1, 2, 2, 3, 3, 3]
    // batch(3): [[1, 2, 2], [3, 3, 3]]
    const source = new PassThrough({ objectMode: true });
    const composed = composeStreams(
      source,
      flatMap(async function* (n) {
        for (let i = 0; i < n; i++) yield n;
      }),
      batch(3),
    );

    const results = [];
    composed.on('data', (chunk) => results.push(chunk));
    composed.on('end', () => {
      clearTimeout(timeout);
      try {
        assert.strictEqual(
          results.length,
          2,
          `Expected 2 batches, got ${results.length}: ${JSON.stringify(results)}`,
        );
        assert.deepStrictEqual(results[0], [1, 2, 2]);
        assert.deepStrictEqual(results[1], [3, 3, 3]);
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    composed.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    composed.write(1);
    composed.write(2);
    composed.write(3);
    composed.end();
  });

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------
async function main() {
  const testName = process.argv[2];

  if (testName && testName !== 'all' && tests[testName]) {
    try {
      await tests[testName]();
      console.log(`PASS: ${testName}`);
      process.exit(0);
    } catch (err) {
      console.error(`FAIL: ${testName} — ${err.message}`);
      if (err.stack) console.error(err.stack);
      process.exit(1);
    }
  } else if (!testName || testName === 'all') {
    let passed = 0;
    let failed = 0;
    const failures = [];

    for (const [name, fn] of Object.entries(tests)) {
      try {
        await fn();
        console.log(`PASS: ${name}`);
        passed++;
      } catch (err) {
        console.error(`FAIL: ${name} — ${err.message}`);
        failed++;
        failures.push({ name, error: err.message });
      }
    }

    console.log(`\n${passed} passed, ${failed} failed`);
    if (failures.length > 0) {
      console.log('Failures:');
      for (const f of failures) {
        console.log(`  - ${f.name}: ${f.error}`);
      }
    }
    process.exit(failed > 0 ? 1 : 0);
  } else {
    console.error(`Unknown test: ${testName}`);
    console.error(`Available tests: ${Object.keys(tests).join(', ')}`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Test runner error:', err);
  process.exit(1);
});

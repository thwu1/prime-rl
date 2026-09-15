import * as fs from 'fs';
import * as assert from 'assert';
import { TestScheduler } from 'rxjs/testing';
import { bufferTime } from '../src/bufferTime';


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
    console.log(`  PASS: ${name}`);
  } catch (e: any) {
    results.push({ name, passed: false, error: e.message || String(e) });
    console.log(`  FAIL: ${name}`);
    console.log(`        ${(e.message || String(e)).split('\n')[0]}`);
  }
}

function createScheduler(): TestScheduler {
  return new TestScheduler((actual: any, expected: any) => {
    assert.deepStrictEqual(actual, expected);
  });
}

console.log('Running bufferTime marble tests...\n');

// ---------------------------------------------------------------------------
// Test 1: Basic interval buffering
// Values are collected for bufferTimeSpan ms, then emitted as an array.
// On source completion, remaining buffer is flushed.
// ---------------------------------------------------------------------------
test('should emit buffers at intervals', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable, expectSubscriptions }) => {
    const source = cold('---a---b---c---d---e---f---g-----|');
    const subs =        '^--------------------------------!';
    const t = time(      '----------|');
    const expected =    '----------w---------x---------y--(z|)';
    const values = {
      w: ['a', 'b'],
      x: ['c', 'd', 'e'],
      y: ['f', 'g'],
      z: [] as string[],
    };

    const result = source.pipe(bufferTime(t, null, Infinity, scheduler));

    expectObservable(result).toBe(expected, values);
    expectSubscriptions(source.subscriptions).toBe(subs);
  });
});

// ---------------------------------------------------------------------------
// Test 2: Overlapping creation interval
// With bufferCreationInterval, new buffers open periodically. Each closes
// after bufferTimeSpan. Buffers overlap, so a single value can appear in
// multiple emitted arrays.
// ---------------------------------------------------------------------------
test('should handle overlapping buffers with creation interval', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable, expectSubscriptions }) => {
    const source = cold('-a--b---c---d--e--f---g----h------------|');
    const subs =        '^---------------------------------------!';
    const t = time(      '----------|');
    const interval = time('-------|');
    const expected =    '----------w------x------y------z------v-(u|)';
    const values = {
      w: ['a', 'b', 'c'],
      x: ['c', 'd', 'e'],
      y: ['e', 'f', 'g'],
      z: ['g', 'h'],
      v: [] as string[],
      u: [] as string[],
    };

    const result = source.pipe(bufferTime(t, interval, Infinity, scheduler));

    expectObservable(result).toBe(expected, values);
    expectSubscriptions(source.subscriptions).toBe(subs);
  });
});

// ---------------------------------------------------------------------------
// Test 3: maxBufferSize causes early emission
// When a buffer reaches maxBufferSize elements, it is emitted immediately.
// In single-buffer mode, a new buffer starts right after the early emission.
// ---------------------------------------------------------------------------
test('should emit buffers at intervals or when buffer is full', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable, expectSubscriptions }) => {
    const source = cold('---a---b---c---d---e---f---g-----|');
    const subs =        '^--------------------------------!';
    const t = time(      '----------|');
    const expected =    '-------w-------x-------y---------(z|)';
    const values = {
      w: ['a', 'b'],
      x: ['c', 'd'],
      y: ['e', 'f'],
      z: ['g'],
    };

    const result = source.pipe(bufferTime(t, null, 2, scheduler));

    expectObservable(result).toBe(expected, values);
    expectSubscriptions(source.subscriptions).toBe(subs);
  });
});

// ---------------------------------------------------------------------------
// Test 4: Error propagation
// When the source errors, the error is forwarded and buffers are discarded.
// ---------------------------------------------------------------------------
test('should forward source errors and discard buffers', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable, expectSubscriptions }) => {
    const source = cold('---a---b---c---#');
    const subs =        '^--------------!';
    const t = time(      '----------|');
    const expected =    '----------w----#';
    const values = {
      w: ['a', 'b'],
    };

    const result = source.pipe(bufferTime(t, null, Infinity, scheduler));

    expectObservable(result).toBe(expected, values);
    expectSubscriptions(source.subscriptions).toBe(subs);
  });
});

// ---------------------------------------------------------------------------
// Test 5: Empty source
// An immediately-completing source should emit its (empty) buffer and complete.
// ---------------------------------------------------------------------------
test('should handle empty source', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable, expectSubscriptions }) => {
    const source = cold('|');
    const subs =        '(^!)';
    const t = time(      '----------|');
    const expected =    '(w|)';
    const values = { w: [] as string[] };

    const result = source.pipe(bufferTime(t, null, Infinity, scheduler));

    expectObservable(result).toBe(expected, values);
    expectSubscriptions(source.subscriptions).toBe(subs);
  });
});

// ---------------------------------------------------------------------------
// Test 6: Combined creation interval and maxBufferSize
// Overlapping buffers with a max size: each buffer emits early when full
// or on its close timer, whichever comes first.
// ---------------------------------------------------------------------------
test('should combine creation interval with maxBufferSize', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable }) => {
    const source = cold('---a---b---c----d----e----f----g----h----i----(k|)');
    const t = time(      '---------------------|');
    const interval = time('--------------------|');
    const expected =    '----------------x-------------------y---------(z|)';
    const values = {
      x: ['a', 'b', 'c', 'd'],
      y: ['e', 'f', 'g', 'h'],
      z: ['i', 'k'],
    };

    const result = source.pipe(bufferTime(t, interval, 4, scheduler));

    expectObservable(result).toBe(expected, values);
  });
});

// ---------------------------------------------------------------------------
// Test 7: Source completion flushes remaining buffer
// If the source completes before the buffer timer fires, the remaining
// buffer is emitted and the output completes.
// ---------------------------------------------------------------------------
test('should flush remaining buffer on source completion', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable, expectSubscriptions }) => {
    const source = cold('---a---b---|');
    const subs =        '^----------!';
    const t = time(      '--------------------|');
    const expected =    '-----------(w|)';
    const values = {
      w: ['a', 'b'],
    };

    const result = source.pipe(bufferTime(t, null, Infinity, scheduler));

    expectObservable(result).toBe(expected, values);
    expectSubscriptions(source.subscriptions).toBe(subs);
  });
});

// ---------------------------------------------------------------------------
// Test 8: Early unsubscription cleans up timers
// When subscribers unsubscribe, the source subscription and all scheduled
// timers should be cleaned up. No further buffers are emitted.
// ---------------------------------------------------------------------------
test('should clean up on early unsubscription', () => {
  const scheduler = createScheduler();
  scheduler.run(({ cold, time, expectObservable, expectSubscriptions }) => {
    const source = cold('---a---b---c---d---e---f---g-----|');
    const subs =        '^----------------!';
    const unsub =       '-----------------!';
    const t = time(      '----------|');
    const expected =    '----------w------';
    const values = {
      w: ['a', 'b'],
    };

    const result = source.pipe(bufferTime(t, null, Infinity, scheduler));

    expectObservable(result, unsub).toBe(expected, values);
    expectSubscriptions(source.subscriptions).toBe(subs);
  });
});

// ---------------------------------------------------------------------------
// Write results
// ---------------------------------------------------------------------------
const resultPath = '/app/test-results.json';
fs.writeFileSync(resultPath, JSON.stringify(results, null, 2));

const passed = results.filter(r => r.passed).length;
const failed = results.filter(r => !r.passed).length;
console.log(`\n${passed} passed, ${failed} failed out of ${results.length} tests`);
process.exit(failed > 0 ? 1 : 0);

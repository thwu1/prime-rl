`/app/src/compose.ts` exports `composeStreams` and `/app/src/operators.ts` exports `batch`, `scan`, `splitLines`, `flatMap`, and `deduplicate`. Both files have defects. Fix all issues so the system satisfies these requirements:

**`composeStreams(...stages): Duplex`**

Accepts 2–8 stages: stream objects (`Transform`, `PassThrough`, `Duplex`) or async generator functions `(source: AsyncIterable<any>) => AsyncGenerator<any>`. Returns a `Duplex` writing to the head stage and reading from the tail.

The composed stream's `writableObjectMode` and `readableObjectMode` must match the head and tail stages respectively. Its `writableHighWaterMark` and `readableHighWaterMark` must inherit from head and tail.

Backpressure: the composed stream resumes writing only when the head signals readiness. End-of-stream: `end` fires after the tail finishes producing data. Finalization: `finish` fires only after all data drains through every stage. Errors in any stage—including async generators—surface as `error` on the composed stream. Destroying the composed stream destroys all internal stages without crashing on already-destroyed stages.

**`batch(size: number): Transform`**

ObjectMode Transform collecting incoming items into arrays of `size`. Partial batches (fewer than `size` remaining items) are flushed on stream end. Must not emit empty arrays.

**`scan<T,R>(fn, seed)`**

Returns an async generator stage for `composeStreams`. For each input value, computes `fn(acc, val)`, updates the accumulator, and yields the new value. Supports both sync and async reducers.

**`splitLines(): Transform`**

Accepts Buffer/string input and emits individual line strings split on `\n` in `readableObjectMode`. Lines spanning chunk boundaries are correctly assembled. Trailing content without a final newline is flushed on stream end. Empty strings are not emitted.

**`flatMap<T,R>(fn: (item: T) => AsyncIterable<R>): Transform`**

ObjectMode Transform that maps each input through an async-iterable-returning function, emitting all yielded items. Items from successive inputs must not interleave: the iterable for input N is fully consumed before input N+1 begins. Errors from the async iterable surface on the stream.

**`deduplicate<T>(keyFn: (item: T) => string, windowSize: number): Transform`**

ObjectMode Transform suppressing duplicate items within a sliding window of the last `windowSize` unique items. Uses `keyFn` to derive a deduplication key. Items whose key has been evicted from the window may pass through again.

**Build and test:**
```
cd /app && npm install && npx tsc
node /tests/test_compose.js all
```

All 24 tests must pass: `simple_composition`, `object_mode`, `backpressure`, `error_propagation`, `end_forwarding`, `final_waits`, `destroy_cleanup`, `three_stage`, `async_generator_stage`, `generator_error`, `mixed_pipeline`, `hwm_inheritance`, `batch_full`, `batch_partial_flush`, `scan_accumulation`, `split_lines_basic`, `split_lines_boundary`, `composed_pipeline`, `flatmap_expand`, `flatmap_ordering`, `flatmap_error`, `deduplicate_basic`, `deduplicate_window`, `advanced_pipeline`.

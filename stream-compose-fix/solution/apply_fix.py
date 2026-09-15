#!/usr/bin/env python3
"""
Apply all fixes to the broken composeStreams and operators implementations.

"""

FIXED_COMPOSE_TS = r'''import { Duplex, Transform, Readable, Writable, finished } from 'node:stream';


type StreamStage = Readable | Writable | Transform | Duplex;
type GeneratorStage = (
  source: AsyncIterable<any>,
) => AsyncGenerator<any, void, undefined>;
type Stage = StreamStage | GeneratorStage;

/**
 * Composes multiple stages into a single Duplex stream.
 * Stages can be stream objects or async generator functions.
 *
 * The composed stream's writable side feeds data into the first stage (head),
 * data flows through intermediate stages via pipe, and the composed stream's
 * readable side reads from the last stage (tail).
 */
export function composeStreams(...stages: Stage[]): Duplex {
  if (stages.length < 2) {
    throw new Error('composeStreams requires at least 2 stages');
  }

  // Normalize: wrap async generator functions into Duplex streams
  const normalized: StreamStage[] = stages.map((stage) => {
    if (typeof stage === 'function') {
      return wrapGenerator(stage as GeneratorStage);
    }
    return stage as StreamStage;
  });

  const head = normalized[0];
  const tail = normalized[normalized.length - 1];

  // Wire up the internal pipeline: each stage pipes to the next
  for (let i = 0; i < normalized.length - 1; i++) {
    (normalized[i] as Readable).pipe(normalized[i + 1] as Writable);
  }

  const writable = isStreamWritable(head);
  const readable = isStreamReadable(tail);

  let ondrain: ((err?: Error | null) => void) | null = null;
  let onfinish: ((err?: Error | null) => void) | null = null;

  // FIX: Inherit objectMode and highWaterMark from head/tail
  const composed = new Duplex({
    writableObjectMode: !!(head as any).writableObjectMode,
    readableObjectMode: !!(tail as any).readableObjectMode,
    writableHighWaterMark: (head as any).writableHighWaterMark,
    readableHighWaterMark: (tail as any).readableHighWaterMark,
    writable,
    readable,
  } as any);

  // === Writable side: proxy writes to head ===
  if (writable) {
    composed._write = function (
      chunk: any,
      encoding: BufferEncoding,
      callback: (err?: Error | null) => void,
    ): void {
      if ((head as Writable).write(chunk, encoding)) {
        callback();
      } else {
        ondrain = callback;
      }
    };

    // FIX: Defer _final callback until pipeline fully drains
    composed._final = function (
      callback: (err?: Error | null) => void,
    ): void {
      (head as Writable).end();
      onfinish = callback;
    };

    // FIX: Use finished() on tail to detect pipeline completion
    finished(tail as any, (err) => {
      if (onfinish) {
        const cb = onfinish;
        onfinish = null;
        cb(err);
      }
    });

    // FIX: Invoke the drain callback, not just clear it
    head.on('drain', function () {
      if (ondrain) {
        const cb = ondrain;
        ondrain = null;
        cb();
      }
    });
  }

  // === Readable side: proxy reads from tail ===
  if (readable) {
    composed._read = function (): void {
      (tail as Readable).resume();
    };

    tail.on('data', function (chunk: any) {
      if (!composed.push(chunk)) {
        (tail as Readable).pause();
      }
    });

    // FIX: Forward end from tail to signal EOF on composed stream
    (tail as Readable).on('end', function () {
      composed.push(null);
    });
  }

  // FIX: Propagate errors to composed stream instead of just logging
  for (let i = 0; i < normalized.length; i++) {
    normalized[i].on('error', (err: Error) => {
      if (!composed.destroyed) {
        composed.destroy(err);
      }
    });
  }

  // FIX: Destroy all internal stages when composed stream is destroyed
  composed._destroy = function (
    err: Error | null,
    callback: (err?: Error | null) => void,
  ): void {
    ondrain = null;
    onfinish = null;
    for (const s of normalized) {
      if (!s.destroyed) {
        s.destroy(err || undefined);
      }
    }
    callback(err);
  };

  return composed;
}

/**
 * Wraps an async generator function into a Duplex stream suitable
 * for use as a pipeline stage.
 *
 * The generator receives an AsyncIterable yielding chunks from the
 * writable side, and its yields are pushed to the readable side.
 */
function wrapGenerator(genFn: GeneratorStage): Duplex {
  const inputBuffer: Array<{ chunk: any; cb: () => void }> = [];
  let inputEnded = false;
  let inputWaiter: (() => void) | null = null;

  // Async iterable that exposes writable-side chunks to the generator
  const source: AsyncIterable<any> = {
    [Symbol.asyncIterator]() {
      return {
        async next(): Promise<IteratorResult<any>> {
          while (inputBuffer.length === 0) {
            if (inputEnded) return { value: undefined, done: true };
            await new Promise<void>((r) => {
              inputWaiter = r;
            });
          }
          const entry = inputBuffer.shift()!;
          entry.cb();
          return { value: entry.chunk, done: false };
        },
      };
    },
  };

  // FIX: Enable objectMode so arbitrary values pass without coercion
  const duplex = new Duplex({
    objectMode: true,
    write(
      chunk: any,
      _enc: BufferEncoding,
      cb: (err?: Error | null) => void,
    ): void {
      inputBuffer.push({ chunk, cb: () => cb() });
      if (inputWaiter) {
        const w = inputWaiter;
        inputWaiter = null;
        w();
      }
    },
    final(cb: (err?: Error | null) => void): void {
      inputEnded = true;
      if (inputWaiter) {
        const w = inputWaiter;
        inputWaiter = null;
        w();
      }
      generatorDone.then(() => cb()).catch((err) => cb(err as Error));
    },
    read(): void {},
  });

  const generatorDone = (async () => {
    const gen = genFn(source);
    for await (const value of gen) {
      duplex.push(value);
    }
    duplex.push(null);
  })();

  // FIX: Catch generator errors and propagate via destroy
  generatorDone.catch((err) => {
    duplex.destroy(err);
  });

  return duplex;
}

function isStreamWritable(stream: StreamStage): boolean {
  return (
    typeof (stream as any).write === 'function' &&
    (stream as any).writable !== false
  );
}

function isStreamReadable(stream: StreamStage): boolean {
  return (
    typeof (stream as any).read === 'function' &&
    (stream as any).readable !== false
  );
}
'''

FIXED_OPERATORS_TS = r'''import { Transform } from 'node:stream';


type GeneratorStage<T = any, R = any> = (
  source: AsyncIterable<T>,
) => AsyncGenerator<R, void, undefined>;

/**
 * Returns an objectMode Transform that collects incoming items into
 * arrays of `size`. When the stream ends, any remaining items are
 * flushed as a partial batch.
 */
export function batch(size: number): Transform {
  let buffer: any[] = [];
  return new Transform({
    objectMode: true,
    transform(
      chunk: any,
      _enc: BufferEncoding,
      cb: (err?: Error | null, data?: any) => void,
    ): void {
      buffer.push(chunk);
      if (buffer.length >= size) {
        this.push(buffer.splice(0, size));
      }
      cb();
    },
    flush(cb: (err?: Error | null) => void): void {
      if (buffer.length > 0) {
        this.push(buffer);
        buffer = [];
      }
      cb();
    },
  });
}

/**
 * Returns an async generator stage compatible with composeStreams.
 * For each input value, applies fn(accumulator, value), updates the
 * accumulator, and yields the new accumulator.
 */
export function scan<T, R>(
  fn: (acc: R, val: T) => R | Promise<R>,
  seed: R,
): GeneratorStage<T, R> {
  return async function* (
    source: AsyncIterable<T>,
  ): AsyncGenerator<R, void, undefined> {
    let acc = seed;
    for await (const val of source) {
      const result = fn(acc, val);
      const resolved = result instanceof Promise ? await result : result;
      acc = resolved;
      yield acc;
    }
  };
}

/**
 * Returns a Transform that splits Buffer/string input into individual
 * lines on '\n'. Lines spanning chunk boundaries are correctly assembled.
 * Trailing content without a final newline is flushed on stream end.
 * Operates in readableObjectMode (each push is a single line string).
 */
export function splitLines(): Transform {
  let partial = '';
  return new Transform({
    readableObjectMode: true,
    transform(
      chunk: any,
      _enc: BufferEncoding,
      cb: (err?: Error | null) => void,
    ): void {
      const str = partial + chunk.toString();
      const lines = str.split('\n');
      partial = lines.pop()!;
      for (const line of lines) {
        if (line.length > 0) {
          this.push(line);
        }
      }
      cb();
    },
    flush(cb: (err?: Error | null) => void): void {
      if (partial.length > 0) {
        this.push(partial);
        partial = '';
      }
      cb();
    },
  });
}

/**
 * Returns an objectMode Transform that maps each input item through
 * an async-iterable-returning function, emitting all yielded items
 * in order. Items from successive inputs do not interleave: the
 * iterable for chunk N is fully consumed before chunk N+1 begins.
 * Errors from the async iterable surface on the stream.
 */
export function flatMap<T, R>(
  fn: (item: T) => AsyncIterable<R>,
): Transform {
  return new Transform({
    objectMode: true,
    transform(
      chunk: T,
      _enc: BufferEncoding,
      cb: (err?: Error | null) => void,
    ): void {
      const self = this;
      (async () => {
        try {
          for await (const item of fn(chunk)) {
            self.push(item);
          }
          cb();
        } catch (err) {
          cb(err as Error);
        }
      })();
    },
  });
}

/**
 * Returns an objectMode Transform that suppresses duplicate items
 * within a sliding window of the last `windowSize` unique items.
 * Uses `keyFn` to derive a string key for each item.
 * Items whose key has left the window may pass through again.
 */
export function deduplicate<T>(
  keyFn: (item: T) => string,
  windowSize: number,
): Transform {
  const seen = new Set<string>();
  const keys: string[] = [];
  return new Transform({
    objectMode: true,
    transform(
      chunk: T,
      _enc: BufferEncoding,
      cb: (err?: Error | null, data?: any) => void,
    ): void {
      const key = keyFn(chunk as any);
      if (seen.has(key)) {
        cb();
      } else {
        seen.add(key);
        keys.push(key);
        while (keys.length > windowSize) {
          const old = keys.shift()!;
          seen.delete(old);
        }
        cb(null, chunk as any);
      }
    },
  });
}
'''

with open('/app/src/compose.ts', 'w') as f:
    f.write(FIXED_COMPOSE_TS.lstrip('\n'))

with open('/app/src/operators.ts', 'w') as f:
    f.write(FIXED_OPERATORS_TS.lstrip('\n'))

print("All fixes applied:")
print("  compose.ts (9 fixes):")
print("    - Object mode inheritance from head/tail")
print("    - HighWaterMark inheritance from head/tail")
print("    - Drain callback invocation")
print("    - End event forwarding from tail")
print("    - Error propagation to composed stream")
print("    - _final deferral with finished() listener")
print("    - Stage destruction in _destroy with destroyed-flag guard")
print("    - objectMode: true on generator wrapper Duplex")
print("    - Generator error catch and propagation")
print("  operators.ts (11 fixes):")
print("    - batch: collect to size before emitting, add _flush for partial")
print("    - scan: yield resolved value, update accumulator")
print("    - splitLines: readableObjectMode, save partial via pop(), add _flush")
print("    - flatMap: defer callback until async iteration completes, catch errors")
print("    - deduplicate: add objectMode, implement sliding window eviction")

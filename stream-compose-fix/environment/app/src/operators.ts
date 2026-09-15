import { Transform } from 'node:stream';


type GeneratorStage<T = any, R = any> = (
  source: AsyncIterable<T>,
) => AsyncGenerator<R, void, undefined>;

/**
 * Returns an objectMode Transform that collects incoming items into
 * arrays of `size`. When the stream ends, any remaining items are
 * flushed as a partial batch.
 */
export function batch(size: number): Transform {
  const buffer: any[] = [];
  return new Transform({
    objectMode: true,
    transform(
      chunk: any,
      _enc: BufferEncoding,
      cb: (err?: Error | null, data?: any) => void,
    ): void {
      buffer.push(chunk);
      cb(null, [chunk]);
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
      yield seed;
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
    transform(
      chunk: any,
      _enc: BufferEncoding,
      cb: (err?: Error | null) => void,
    ): void {
      const str = partial + chunk.toString();
      const lines = str.split('\n');
      partial = '';
      for (const line of lines) {
        if (line.length > 0) {
          this.push(line);
        }
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
      const iter = fn(chunk);
      (async () => {
        for await (const item of iter) {
          self.push(item);
        }
      })();
      cb();
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
  return new Transform({
    transform(
      chunk: T,
      _enc: BufferEncoding,
      cb: (err?: Error | null) => void,
    ): void {
      const key = keyFn(chunk as any);
      if (seen.has(key)) {
        cb();
      } else {
        seen.add(key);
        cb(null, chunk as any);
      }
    },
  });
}

import { Duplex, Transform, Readable, Writable, finished } from 'node:stream';


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

  // Create the composed Duplex that proxies head (writable) and tail (readable)
  const composed = new Duplex({
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

    composed._final = function (
      callback: (err?: Error | null) => void,
    ): void {
      (head as Writable).end();
      callback();
    };

    // Resume writes when head signals it can accept more data
    head.on('drain', function () {
      if (ondrain) {
        ondrain = null;
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
  }

  // === Error handling across pipeline stages ===
  for (let i = 0; i < normalized.length; i++) {
    normalized[i].on('error', (err: Error) => {
      if (process.env.COMPOSE_DEBUG) {
        process.stderr.write(
          `[composeStreams] error in stage ${i}: ${err.message}\n`,
        );
      }
    });
  }

  // === Cleanup on destroy ===
  composed._destroy = function (
    err: Error | null,
    callback: (err?: Error | null) => void,
  ): void {
    ondrain = null;
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

  const duplex = new Duplex({
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

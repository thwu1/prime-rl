A broken `bufferTime` operator implementation exists at `/app/src/bufferTime.ts`. This pipeable RxJS operator collects source Observable values into arrays based on time windows. Fix the implementation so all marble-diagram tests pass.

**Operator signatures:**

```typescript
bufferTime<T>(span: number, scheduler?: SchedulerLike): OperatorFunction<T, T[]>
bufferTime<T>(span: number, creationInterval: number | null, scheduler?: SchedulerLike): OperatorFunction<T, T[]>
bufferTime<T>(span: number, creationInterval: number | null, maxBufferSize: number, scheduler?: SchedulerLike): OperatorFunction<T, T[]>
```

**Semantics:**

- Collect source values into buffer arrays. With only `span`, emit the buffer every `span` ms and start a new one.
- When `creationInterval` is non-null and >= 0, open a new buffer every `creationInterval` ms. Each buffer independently closes after `span` ms. Multiple buffers may overlap; each incoming value is pushed into every currently active buffer.
- When `maxBufferSize` is specified, any buffer reaching that count emits immediately. In single-buffer mode (no creation interval), a replacement buffer starts after early emission.
- On source completion, flush all active buffers in creation order, then complete the output.
- On source error, discard all buffers and forward the error.
- Use the `scheduler` parameter for all timing if provided; default to `asyncScheduler`.

**Constraints:**

- Do not import from `rxjs/operators` or `rxjs/internal`. Only `rxjs` top-level exports are allowed.
- Do not install additional npm packages beyond what is in `/app/package.json`.
- The file must export `bufferTime` as a named export with the overloaded signatures above.

**Verification:**

```
cd /app && npm install && npx tsx test/run-tests.ts
```

All test cases in `/app/test/run-tests.ts` must pass. Tests use RxJS `TestScheduler` with marble-diagram assertions to verify emission timing, buffer contents, overlapping window behavior, subscription lifecycle, error propagation, and completion semantics.

A `RingBuffer<T>` implementation at `/app/src/ring-buffer.ts` contains correctness bugs that surface under certain operation sequences. The project uses TypeScript with Vitest and fast-check (see `/app/package.json`; run `npm install` first).

Fix all bugs and write a property test suite at `/app/src/ring-buffer.test.ts` that verifies the implementation.

## Ring Buffer Contract

`RingBuffer<T>` is a fixed-capacity FIFO queue constructed with `{ capacity: number, policy?: OverflowPolicy }` where `OverflowPolicy = 'drop-oldest' | 'drop-newest' | 'reject'` (default `'drop-oldest'`).

**Operations:**

- `push(item: T): boolean` -- Enqueue at tail. At capacity: `'drop-oldest'` evicts head and accepts (`true`); `'reject'` and `'drop-newest'` refuse (`false`).
- `pop(): T | undefined` -- Dequeue head, or `undefined` if empty.
- `peek(offset?: number): T | undefined` -- Non-destructive read at `offset` from head (default 0). `undefined` when out of range.
- `pushMany(items: T[]): number` -- Push each item in order; return the count actually inserted into the buffer.
- `toArray(): T[]` -- Snapshot of all items head-to-tail, without mutation.
- `setPolicy(p: OverflowPolicy): void` -- Change overflow policy at runtime.
- `clear(): void` -- Empty the buffer, reset state.
- Getters: `size`, `capacity`, `policy`, `isEmpty`, `isFull`.

## Success Criteria

1. `npx vitest run` exits 0.
2. `/app/src/ring-buffer.test.ts` uses fast-check to verify the buffer's correctness across arbitrary sequences of operations by testing against a reference model.
3. The ring buffer satisfies the contract above for all valid inputs.

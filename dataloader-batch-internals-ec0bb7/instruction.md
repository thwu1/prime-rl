The project at `/app/` is a multi-module TypeScript DataLoader library. Fix all defects — in configuration and source code — so that `cd /app && npm install && npx jest --forceExit` exits with code 0 and all tests pass.

**Project layout:**
- `/app/src/dataloader.ts` — Core `DataLoader<K, V, C>` class
- `/app/src/lru-cache.ts` — `LRUCacheMap<K, V>` implementing `CacheMap`
- `/app/src/batch-coalescer.ts` — `BatchCoalescer` for coordinating dispatch timing
- `/app/src/request-scope.ts` — `RequestScope` factory for creating coordinated loaders
- `/app/tsconfig.json`, `/app/jest.config.js`, `/app/package.json` — build/test config

**DataLoader contracts:**

All `load()` calls within one execution frame — including from chained promise continuations — must collect into a single batch. The default scheduler must defer dispatch until after all microtask-queued promise jobs complete.

Cache-hit `load()` calls must not resolve before the current batch dispatches. Cached and fresh values resolve atomically in the same microtask.

Batches must contain at most `maxBatchSize` keys; overflow forms a separately-scheduled batch.

If `batchLoadFn` returns an array whose length differs from the keys array, reject every promise with a `TypeError` including keys and values.

On batch failure (throw, non-Promise return, or rejection), remove every key from the cache so subsequent loads retry.

`prime(key, error)` where error is an `Error` must cache a rejected promise without triggering unhandled-rejection warnings.

**LRUCacheMap contracts:**

Implements `CacheMap<K, V>` with bounded capacity. `get` and `set`-for-existing-key promote to most-recently-used. At capacity, `set` for a new key evicts the least-recently-used entry.

**BatchCoalescer contracts:**

`createScheduler()` returns a `batchScheduleFn`-compatible function. Schedulers from the same coalescer share one dispatch queue using post-promise-job deferral. Re-entrant dispatch callbacks (from batch execution) must schedule a new flush, never be dropped.

**RequestScope contracts:**

`createLoader(name, batchFn, options?)` produces a `DataLoader` whose dispatch routes through the scope's `BatchCoalescer`. All scope loaders share one scheduler. Each loader must use a `LRUCacheMap` bounded to the scope's `maxCacheSize`.

`dispose()` must invalidate all cached data across every loader before releasing references. Existing loader references must observe empty caches post-disposal. `createLoader` on a disposed scope must throw.

**API surface:**
- `DataLoader<K, V, C>`: `load`, `loadMany`, `clear`, `clearAll`, `prime`, `name`
- `LRUCacheMap<K, V>`: `get`, `set`, `delete`, `clear`
- `BatchCoalescer`: `createScheduler()`
- `RequestScope`: `createLoader(name, batchFn, options?)`, `dispose()`, `disposed`

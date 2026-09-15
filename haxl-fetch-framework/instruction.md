`/app/MicroHaxl.hs` contains a concurrent data-fetching framework module. Make it compile with GHC and satisfy the behavioral contract below. The test suite at `/tests/test_state.py` verifies all requirements.

**Module exports**: `Fetch`, `Result`, `BlockedFetch`, `ResultVar` (with `mkResultVar`, `putResult`, `putFailure`, `putSuccess`), `DataSource`, `DataSourceState`, `StateStore` (with `emptyStateStore`, `stateSet`, `stateGet`), `Env` (with `initEnv`), `runFetch`, `Stats` (with `emptyStats`), `CacheKey`, `dataFetch`, `preFetch`, `pairFetch`, `traverseFetch`.

**Behavioral contract**:

*Batching*: Independent `dataFetch` calls combined via Applicative operations, `pairFetch`, or `traverseFetch` must all be discovered and dispatched in a single fetch round. Monadic `>>=` may introduce additional rounds.

*Deduplication*: Identical requests within a computation produce exactly one `BlockedFetch`. Subsequent references reuse the cached result.

*Cache type safety*: Requests of different types with identical string representations must not collide.

*Batch dispatch*: All `BlockedFetch` values sharing a data source must be passed to one `fetch` call per round. Different data sources in the same round must be dispatched concurrently.

*Exception safety*: If a data source `fetch` throws, every unfilled `ResultVar` in that batch receives the exception. The scheduler must never deadlock.

*Pre-fetch*: `preFetch req val` seeds the cache so that a subsequent `dataFetch req` returns `val` without dispatching a fetch.

*Statistics*: `runFetch` returns `Stats` with: fetch round count, total individual fetches dispatched, and per-data-source fetch counts in `statsDatasources`.

*State store*: `StateStore` maps data source types to their `SourceState`. `initEnv` accepts a `StateStore`. Dispatch looks up the correct state for each data source.

All tests in `/tests/test_state.py` must pass.

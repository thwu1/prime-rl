The project at `/app/fuzzcorp/` defines interfaces for a coverage-guided fuzzing framework (Python 3.12+). Three modules — `coverage.py`, `corpus.py`, `scheduler.py` — contain stubs raising `NotImplementedError`. Implement them so the test suite passes.

**CoverageCollector** (`/app/fuzzcorp/coverage.py`): Context manager collecting branch-level coverage via `Branch(Location, Location)` with filename, line, and column. Must exclude stdlib, generated/frozen code (`<...>` filenames), and caller-specified prefixes. Re-entering resets observed branches without permanently disabling tracing of any code location.

**Corpus** (`/app/fuzzcorp/corpus.py`): Minimal covering set under shortlex ordering with reference-counted fingerprint-to-input mapping. Inputs shared across multiple fingerprints must not be evicted prematurely. Per-branch observation counts reset when the corpus changes (new fingerprint or shorter replacement).

**FuzzScheduler** (`/app/fuzzcorp/scheduler.py`): Time allocation across fuzz targets proportional to behavior-discovery rate estimates. Power schedule weights corpus entries by inverse count of their rarest branch. Requires numerically stable softmax over arbitrary-magnitude scores.

Types in `/app/fuzzcorp/types.py`, target functions in `/app/targets.py`, method signatures in the stubs.
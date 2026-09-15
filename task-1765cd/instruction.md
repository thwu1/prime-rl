A low-latency market data pipeline at `/app/` routes tick data through a bounded SPSC (single-producer single-consumer) queue. Production monitoring reports that the queue's throughput is well below the rate required for the trading SLA, causing message backpressure under load. The root cause has not been identified.

The queue implementation is at `/app/include/spsc_queue.hpp`. Profile the current implementation by building and running the benchmark (`make benchmark && ./build/benchmark` in `/app/`). Examine the source code to diagnose the throughput bottleneck, then re-implement the queue to eliminate it.

The `/app/Makefile` provides build targets `stress_test`, `stress_test_tsan`, and `benchmark`. Supporting source files are at `/app/src/stress_test.cpp` and `/app/src/benchmark.cpp`. If any file is missing from `/app/`, restore it from the backup at `/opt/task_env/`.

## Acceptance criteria for `/app/include/spsc_queue.hpp`

- **No blocking synchronization**: The source code (excluding comments) must contain no blocking primitives — no `mutex`, spinlocks, or condition variables.
- **Data-race free**: `make stress_test_tsan && TSAN_OPTIONS=halt_on_error=1 ./build/stress_test_tsan 500000` must complete with zero ThreadSanitizer warnings.
- **Stress correctness**: `make stress_test && ./build/stress_test 5000000` must print `STRESS_TEST_PASSED`.
- **Throughput**: `make benchmark && ./build/benchmark` must show the implementation achieving at least 2x the ops/sec of the mutex baseline.
- **API preserved**: `push(const T&)`, `consume_one(Func&&)`, `capacity()` with correct FIFO ordering and boundary behavior (full queue rejects push, empty queue rejects consume, correct wrap-around).
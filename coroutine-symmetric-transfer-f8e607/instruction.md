The directory `/app/include/coro/` contains a C++20 header-only coroutine library with four components. Several contain defects and two are declared but unimplemented. All components must work correctly for the test suite to pass.

**Components and their contracts:**

- **`task.hpp`** — Lazy, move-only coroutine task. `task<T>` suspends on creation and executes when `co_await`ed. Must support arbitrary nesting depth, preserve original exception types through `co_await` chains (including `std::runtime_error`, `std::logic_error`, etc.), and sustain loops of 1,000,000 synchronous `co_await` iterations within an 8 MB stack without crashing.

- **`generator.hpp`** — Synchronous pull-based generator. `generator<T>` is iterable with range-for via `begin()`/`end()`. Calling `begin()` must advance the coroutine to the first yielded value. Exceptions thrown inside the generator body must propagate through the iterator to the caller. Destroying a generator mid-iteration must not leak or crash.

- **`sync_wait.hpp`** — Declared but unimplemented. Provide working definitions for `T sync_wait(task<T>)` and `void sync_wait(task<void>)`. Each must drive a task graph to completion on the current thread, return the result, and propagate any stored exception. All task graphs in the test suite complete synchronously on a single thread.

- **`when_all.hpp`** — Declared but unimplemented. Provide a working definition for `task<std::tuple<Ts...>> when_all(task<Ts>... tasks)`. It must `co_await` every provided task and return their results collected in a `std::tuple`. If any task throws, the exception must propagate to the awaiting coroutine.

`/app/example.cpp` demonstrates intended usage of all four components.

**Build:**
```
g++ -std=c++20 -I /app/include -O2 -o prog prog.cpp
```

**Success criteria:** All tests pass when executed by the test harness.

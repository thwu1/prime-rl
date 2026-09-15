Implement a lock-free concurrent signal data structure in C at `/app/signal_tree.c`.

The data structure manages 512 binary signals that can be activated and claimed concurrently by multiple threads without locks or mutexes. The C API is declared in `/app/signal_tree.h`, and a stub file with function signatures already exists at `/app/signal_tree.c`; replace the placeholder logic with a correct implementation.

Behavioral requirements, thread-safety guarantees, and correctness invariants are documented in `/app/spec.md`.

A test harness covering single-threaded correctness and multi-threaded stress scenarios is provided at `/app/test_runner.c`. Build and run with `cd /app && make && ./test_runner`. All 12 tests must pass.
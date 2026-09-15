A lock-free stack (Treiber's algorithm) is provided at `/app/lockfree_stack.hpp`. The `push()` method is correct. The `topAndPop()` method correctly removes nodes via CAS but **leaks every popped node** — naively deleting a node that another thread might still be dereferencing causes use-after-free, so the current code simply never frees.

A concurrent stress test harness is at `/app/test_concurrent.cpp` with a `Makefile`.

Design and implement a complete hazard pointer memory reclamation system in a new file `/app/memory_reclamation.hpp`, then integrate it into the stack's `topAndPop()` by modifying `/app/lockfree_stack.hpp`.

The reclamation system must support at least 128 concurrent threads, be entirely lock-free (no mutexes, spinlocks, or blocking primitives), and use the weakest correct memory ordering for each atomic operation rather than defaulting to sequential consistency everywhere. Popped nodes must actually be reclaimed — not leaked indefinitely. The system must correctly handle hazard pointer slot lifecycle via RAII with safe slot recycling when threads exit.

Verification: `make && ./test_concurrent` and `make test_asan && ASAN_OPTIONS=detect_leaks=0 ./test_asan`
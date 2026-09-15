A C++ project at `/app/` implements a shared-memory SPSC (Single Producer Single Consumer) queue for low-latency inter-process communication. The codebase:

- `/app/include/spsc_queue.h` -- queue header, producer, and consumer
- `/app/include/shm_protocol.h` -- shared-memory segment management
- `/app/include/config.h` -- configuration constants (immutable)
- `/app/stress_test.cpp` -- production readiness suite (immutable)

The readiness suite (`make stress` in `/app/`) currently fails multiple tests due to correctness and design defects in the queue and protocol implementations.

All defects must be identified and fixed so `make stress` passes reliably. A diagnostic report at `/app/analysis.md` must document each issue found, its root cause, the applied fix, and supporting evidence from diagnostic tooling (e.g. sanitizers, disassembly, layout inspection).

`/app/include/config.h` and `/app/stress_test.cpp` must not be modified.
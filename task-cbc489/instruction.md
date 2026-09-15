A C project at `/app/` contains a biased reference counting library based on PEP 703 (Making the Global Interpreter Lock Optional in CPython). The header `/app/include/brc.h` fully specifies the API, data structures, and expected semantics for every function.

The implementation file `/app/src/brc.c` contains only stubs that return zero/NULL/false. Complete all function bodies so that the library is correct under concurrent multi-threaded access from pthreads.

Build with `make` in `/app/`.
`/app/pipeline.cpp` implements a separable Gaussian blur, gradient magnitude computation, multi-level edge classification, and histogram analysis on a deterministically generated 4096x4096 image. The program is functionally correct but contains multiple performance bottlenecks.

Optimize `/app/pipeline.cpp` to achieve at least **2x wall-clock speedup** over the unmodified baseline while producing **bit-identical stdout output** (HASH, EDGES, and all BUCKET lines must match exactly). The program must compile with `g++ -O2 -std=c++17 -lm`.

Build and run: `cd /app && make clean && make && ./pipeline`

Profiling tools available: `valgrind --tool=callgrind`, `/usr/bin/time -v`, compiler flags (`-pg` for gprof), manual `clock_gettime` instrumentation.
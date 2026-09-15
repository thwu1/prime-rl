A C program at `/app/edge_detect.c` implements a multi-stage edge detection pipeline on a 2048x2048 grayscale image: iterative separable Gaussian smoothing, Sobel gradient computation with direction, and sub-pixel gradient-interpolated non-maximum suppression. The pipeline has performance bottlenecks spanning multiple stages and bottleneck categories. Optimize `/app/edge_detect.c` to achieve at least **3x wall-clock speedup** over the unmodified baseline while maintaining numerical correctness.

Both the baseline reference and your optimized version are built from `/app/Makefile` using `make -C /app edge_detect` (your code) and `make -C /app edge_detect_ref` (unmodified baseline). Profiling tools (`valgrind --tool=callgrind`) are available in the environment.

**Constraints:**
- Only modify `/app/edge_detect.c` — do not modify the Makefile, reference source, or input data.
- The program must remain single-threaded.
- Output must match the baseline within floating-point tolerance (max pixel error < 50.0, mean error < 1.0).
- The command-line interface (`./edge_detect input.bin output.bin <smooth_iters>`) and stderr timing format (`TIME: X.XXXX`) must be preserved.
- The binary output format (int32 width, int32 height, float32 pixels) must be preserved.
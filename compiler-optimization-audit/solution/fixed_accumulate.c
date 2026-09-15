/*
 * Fixed version of the accumulate function from target.c.
 *
 * The original suffers from pointer aliasing: since both 'total' and 'data'
 * are int-typed pointers, the compiler must assume they could overlap and
 * therefore stores *total back to memory every loop iteration.
 *
 * Fix: copy *total into a local variable, accumulate there (no aliasing
 * possible with a stack local), then write the result back once after the
 * loop.
 */
void accumulate(int *total, const int *data, int n) {
    int t = *total;
    for (int i = 0; i < n; i++) {
        t += data[i];
    }
    *total = t;
}

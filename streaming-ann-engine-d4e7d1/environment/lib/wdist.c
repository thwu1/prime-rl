/*
 * wdist.c — Weighted squared-L2 distance computation.
 *
 * Compile: gcc -shared -fPIC -O2 -o libwdist.so wdist.c
 *
 */

#include <stdlib.h>
#include <string.h>

typedef struct {
    float *weights;
    int    dim;
} WDistCtx;

/*
 * Create a context initialised with per-dimension weights.
 * Caller is responsible for calling wdist_destroy when done.
 */
void *wdist_create(const float *weights, int dim) {
    WDistCtx *ctx = (WDistCtx *)malloc(sizeof(WDistCtx));
    if (!ctx) return NULL;
    ctx->dim = dim;
    ctx->weights = (float *)malloc((size_t)dim * sizeof(float));
    if (!ctx->weights) { free(ctx); return NULL; }
    memcpy(ctx->weights, weights, (size_t)dim * sizeof(float));
    return ctx;
}

/*
 * Compute weighted squared-L2 distance between vectors a and b.
 *   d(a, b) = sum_i  w_i * (a_i - b_i)^2
 */
float wdist_distance(const void *handle, const float *a, const float *b) {
    const WDistCtx *ctx = (const WDistCtx *)handle;
    float dist = 0.0f;
    int i;
    for (i = 0; i < ctx->dim; i++) {
        float d = a[i] - b[i];
        dist += ctx->weights[i] * d * d;
    }
    return dist;
}

/*
 * Batch distance: compute distance from one query vector to each of n
 * row-major vectors.  Results are written to out[0 .. n-1].
 */
void wdist_batch(const void *handle, const float *query,
                 const float *vectors, int n, float *out) {
    const WDistCtx *ctx = (const WDistCtx *)handle;
    int j, i;
    for (j = 0; j < n; j++) {
        float dist = 0.0f;
        const float *v = vectors + j * ctx->dim;
        for (i = 0; i < ctx->dim; i++) {
            float d = query[i] - v[i];
            dist += ctx->weights[i] * d * d;
        }
        out[j] = dist;
    }
}

/* Free a context previously returned by wdist_create. */
void wdist_destroy(void *handle) {
    WDistCtx *ctx = (WDistCtx *)handle;
    if (ctx) {
        free(ctx->weights);
        free(ctx);
    }
}

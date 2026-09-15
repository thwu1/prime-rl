/*
 * optimized_pipeline.cpp - Optimized Image Processing Pipeline
 *
 * Optimizations applied:
 * 1. Vertical convolution: loop interchange (row-major traversal)
 *    + border/interior split to eliminate bounds checks
 * 2. Horizontal convolution: border/interior split to skip redundant
 *    weight-sum division for interior pixels
 * 3. Gradient: strength reduction — store squared magnitude, skip sqrt()
 * 4. Classification: branchless arithmetic with squared thresholds
 * 5. Histogram: remove unnecessary branch guard
 *
 * Output is bit-identical to the baseline.
 */

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cinttypes>

static const int W = 4096;
static const int H = 4096;
static const int N = W * H;
static const int KRAD = 4;
static const int KSIZE = 2 * KRAD + 1;

static const int KRN[9] = {1, 8, 28, 56, 70, 56, 28, 8, 1};
static const int KSUM = 256;

static void generate_image(uint8_t* img) {
    uint64_t s = 0xDEADBEEFCAFEBABEULL;
    for (int i = 0; i < N; i++) {
        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
        img[i] = (uint8_t)(s >> 56);
    }
}

/* Horizontal conv: border/interior split */
static void convolve_h(const uint8_t* in, int32_t* out) {
    for (int r = 0; r < H; r++) {
        /* Left border */
        for (int c = 0; c < KRAD; c++) {
            int32_t acc = 0, wt = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                int cc = c + k;
                if (cc >= 0) {
                    acc += (int32_t)in[r * W + cc] * KRN[k + KRAD];
                    wt += KRN[k + KRAD];
                }
            }
            out[r * W + c] = acc / wt;
        }
        /* Interior — all taps valid, wt == KSUM */
        for (int c = KRAD; c < W - KRAD; c++) {
            int32_t acc = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                acc += (int32_t)in[r * W + c + k] * KRN[k + KRAD];
            }
            out[r * W + c] = acc / KSUM;
        }
        /* Right border */
        for (int c = W - KRAD; c < W; c++) {
            int32_t acc = 0, wt = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                int cc = c + k;
                if (cc < W) {
                    acc += (int32_t)in[r * W + cc] * KRN[k + KRAD];
                    wt += KRN[k + KRAD];
                }
            }
            out[r * W + c] = acc / wt;
        }
    }
}

/* Vertical conv: row-major traversal + border/interior split */
static void convolve_v(const int32_t* in, int32_t* out) {
    /* Top border rows */
    for (int r = 0; r < KRAD; r++) {
        for (int c = 0; c < W; c++) {
            int32_t acc = 0, wt = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                int rr = r + k;
                if (rr >= 0) {
                    acc += in[rr * W + c] * KRN[k + KRAD];
                    wt += KRN[k + KRAD];
                }
            }
            out[r * W + c] = acc / wt;
        }
    }
    /* Interior — row-major order, no bounds check */
    for (int r = KRAD; r < H - KRAD; r++) {
        for (int c = 0; c < W; c++) {
            int32_t acc = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                acc += in[(r + k) * W + c] * KRN[k + KRAD];
            }
            out[r * W + c] = acc / KSUM;
        }
    }
    /* Bottom border rows */
    for (int r = H - KRAD; r < H; r++) {
        for (int c = 0; c < W; c++) {
            int32_t acc = 0, wt = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                int rr = r + k;
                if (rr < H) {
                    acc += in[rr * W + c] * KRN[k + KRAD];
                    wt += KRN[k + KRAD];
                }
            }
            out[r * W + c] = acc / wt;
        }
    }
}

/* Gradient: squared magnitude (no sqrt) */
static void gradient(const int32_t* blur, int32_t* mag) {
    std::memset(mag, 0, (size_t)N * sizeof(int32_t));
    for (int r = 1; r < H - 1; r++) {
        for (int c = 1; c < W - 1; c++) {
            int32_t gx = blur[r * W + c + 1] - blur[r * W + c - 1];
            int32_t gy = blur[(r + 1) * W + c] - blur[(r - 1) * W + c];
            mag[r * W + c] = gx * gx + gy * gy;
        }
    }
}

/* Branchless classification with squared thresholds.
 * (int32_t)sqrt(v) >= t  iff  v >= t*t  for v >= 0, integer t >= 0.
 * Thresholds: 20->400, 50->2500, 100->10000, 200->40000.
 * Labels: 0, 64, 128, 192, 255. */
static void classify(const int32_t* mag, uint8_t* edges) {
    for (int i = 0; i < N; i++) {
        int32_t v = mag[i];
        edges[i] = (uint8_t)(
            (v >= 400)   * 64 +
            (v >= 2500)  * 64 +
            (v >= 10000) * 64 +
            (v >= 40000) * 63
        );
    }
}

/* Histogram: branchless increment */
static void histogram(const uint8_t* edges, int64_t hist[256]) {
    std::memset(hist, 0, 256 * sizeof(int64_t));
    for (int i = 0; i < N; i++) {
        hist[edges[i]] += (edges[i] > 0);
    }
}

static uint64_t hash_output(const uint8_t* data, int n) {
    uint64_t h = 14695981039346656037ULL;
    for (int i = 0; i < n; i++) {
        h ^= data[i];
        h *= 1099511628211ULL;
    }
    return h;
}

int main() {
    auto* image   = new uint8_t[N];
    auto* hbuf    = new int32_t[N];
    auto* blurred = new int32_t[N];
    auto* mag     = new int32_t[N];
    auto* edges   = new uint8_t[N];
    int64_t hist[256];

    generate_image(image);
    convolve_h(image, hbuf);
    convolve_v(hbuf, blurred);
    gradient(blurred, mag);
    classify(mag, edges);
    histogram(edges, hist);

    uint64_t h = hash_output(edges, N);
    int64_t total = 0;
    for (int i = 1; i < 256; i++) total += hist[i];

    std::printf("HASH: %016" PRIx64 "\n", h);
    std::printf("EDGES: %" PRId64 "\n", total);
    for (int b = 0; b < 256; b += 64) {
        int64_t cnt = 0;
        for (int i = b; i < b + 64 && i < 256; i++) cnt += hist[i];
        std::printf("BUCKET[%03d-%03d]: %" PRId64 "\n", b, b + 63, cnt);
    }

    delete[] image;
    delete[] hbuf;
    delete[] blurred;
    delete[] mag;
    delete[] edges;

    return 0;
}

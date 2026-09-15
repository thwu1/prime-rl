/*
 * pipeline.cpp - Image Processing Pipeline
 *
 * Applies separable Gaussian blur, gradient magnitude computation,
 * multi-level edge classification, and histogram analysis to a
 * deterministically generated 4096x4096 image.
 *
 * Build:  g++ -O2 -std=c++17 -lm -o pipeline pipeline.cpp
 * Run:    ./pipeline
 */

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cinttypes>

static const int W = 4096;
static const int H = 4096;
static const int N = W * H;
static const int KRAD = 4;
static const int KSIZE = 2 * KRAD + 1;

/* Binomial kernel (n=8), sum = 256 */
static const int KRN[9] = {1, 8, 28, 56, 70, 56, 28, 8, 1};
static const int KSUM = 256;

/* ------------------------------------------------------------------ */
/* Deterministic image generation (LCG)                                */
/* ------------------------------------------------------------------ */
static void generate_image(uint8_t* img) {
    uint64_t s = 0xDEADBEEFCAFEBABEULL;
    for (int i = 0; i < N; i++) {
        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
        img[i] = (uint8_t)(s >> 56);
    }
}

/* ------------------------------------------------------------------ */
/* Horizontal 1-D convolution                                          */
/* Handles borders via per-pixel bounds check and weight accumulation.  */
/* For interior pixels the weight sum always equals KSUM, yet the code  */
/* recomputes it every time.                                           */
/* ------------------------------------------------------------------ */
static void convolve_h(const uint8_t* in, int32_t* out) {
    for (int r = 0; r < H; r++) {
        for (int c = 0; c < W; c++) {
            int32_t acc = 0, wt = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                int cc = c + k;
                if (cc >= 0 && cc < W) {
                    acc += (int32_t)in[r * W + cc] * KRN[k + KRAD];
                    wt += KRN[k + KRAD];
                }
            }
            out[r * W + c] = acc / wt;
        }
    }
}

/* ------------------------------------------------------------------ */
/* Vertical 1-D convolution                                            */
/* Traverses columns in the outer loop, rows in the inner loop.        */
/* ------------------------------------------------------------------ */
static void convolve_v(const int32_t* in, int32_t* out) {
    for (int c = 0; c < W; c++) {
        for (int r = 0; r < H; r++) {
            int32_t acc = 0, wt = 0;
            for (int k = -KRAD; k <= KRAD; k++) {
                int rr = r + k;
                if (rr >= 0 && rr < H) {
                    acc += in[rr * W + c] * KRN[k + KRAD];
                    wt += KRN[k + KRAD];
                }
            }
            out[r * W + c] = acc / wt;
        }
    }
}

/* ------------------------------------------------------------------ */
/* Gradient magnitude via Euclidean norm                                */
/* ------------------------------------------------------------------ */
static void gradient(const int32_t* blur, int32_t* mag) {
    std::memset(mag, 0, (size_t)N * sizeof(int32_t));
    for (int r = 1; r < H - 1; r++) {
        for (int c = 1; c < W - 1; c++) {
            int32_t gx = blur[r * W + c + 1] - blur[r * W + c - 1];
            int32_t gy = blur[(r + 1) * W + c] - blur[(r - 1) * W + c];
            mag[r * W + c] = (int32_t)std::sqrt((double)(gx * gx + gy * gy));
        }
    }
}

/* ------------------------------------------------------------------ */
/* Multi-level edge classification                                     */
/* Maps gradient magnitudes to five discrete labels via threshold       */
/* cascade.                                                            */
/* ------------------------------------------------------------------ */
static void classify(const int32_t* mag, uint8_t* edges) {
    for (int i = 0; i < N; i++) {
        int32_t v = mag[i];
        if (v >= 200) {
            edges[i] = 255;
        } else if (v >= 100) {
            edges[i] = 192;
        } else if (v >= 50) {
            edges[i] = 128;
        } else if (v >= 20) {
            edges[i] = 64;
        } else {
            edges[i] = 0;
        }
    }
}

/* ------------------------------------------------------------------ */
/* Histogram of non-zero edge labels                                   */
/* ------------------------------------------------------------------ */
static void histogram(const uint8_t* edges, int64_t hist[256]) {
    std::memset(hist, 0, 256 * sizeof(int64_t));
    for (int i = 0; i < N; i++) {
        if (edges[i] > 0) {
            hist[edges[i]]++;
        }
    }
}

/* ------------------------------------------------------------------ */
/* FNV-1a hash of output array                                         */
/* ------------------------------------------------------------------ */
static uint64_t hash_output(const uint8_t* data, int n) {
    uint64_t h = 14695981039346656037ULL;
    for (int i = 0; i < n; i++) {
        h ^= data[i];
        h *= 1099511628211ULL;
    }
    return h;
}

/* ------------------------------------------------------------------ */
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

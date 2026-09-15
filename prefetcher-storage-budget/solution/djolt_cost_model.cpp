//
// D-JOLT hardware storage cost model.
// Takes (lr_sets, sr_sets, extra_sets) and outputs total prefetcher bits.
// All parameters derived from DJOLT_prefetcher.cc.

#include <cstdio>
#include <cstdlib>
#include <cstdint>

// D-JOLT parameters (from DJOLT_prefetcher.cc constexpr declarations)
static const int SIG_BITS = 23;      // SignatureBits
static const int UBP_BITS = 4;       // UpperBitPtrBits
static const int N_WAYS = 4;         // all tables use 4 ways
static const int N_VECTORS = 2;      // miss vectors per entry
static const int VEC_SIZE = 8;       // bits per vector
static const int LRU_BITS = 2;       // ceil(log2(N_WAYS))

// Fixed (non-table) component costs in bits:
//   LR siggen (FifoRetCnt<7>):   32*7 + ceil(log2(7)) + 32 = 259
//   LR sig queue (distance=12):  23*12 + ceil(log2(12))     = 280
//   SR siggen (FifoRetCnt<4>):   32*4 + ceil(log2(4)) + 32  = 162
//   SR sig queue (distance=4):   23*4 + ceil(log2(4))        = 94
//   Upper bit table (15 entries): (40+1)*15                  = 615
//   Training table (16 entries):  (58+1+2+4)*16              = 1040
//   Monitoring table (16 entries): (58+1+4)*16               = 1008
static const int64_t FIXED_BITS = 259 + 280 + 162 + 94 + 615 + 1040 + 1008;

static bool is_pow2(int64_t n) {
    return n > 0 && (n & (n - 1)) == 0;
}

static int ilog2(int64_t n) {
    int r = 0;
    while (n > 1) { n >>= 1; ++r; }
    return r;
}

static int64_t table_bits(int64_t sets) {
    int tag = SIG_BITS - ilog2(sets);
    int per_entry = tag + (UBP_BITS + 18 + VEC_SIZE) * N_VECTORS + LRU_BITS;
    return static_cast<int64_t>(per_entry) * sets * N_WAYS;
}

int main(int argc, char** argv) {
    if (argc != 4) {
        fprintf(stderr, "Usage: %s lr_sets sr_sets extra_sets\n", argv[0]);
        return 1;
    }

    int64_t vals[3];
    for (int i = 0; i < 3; ++i) {
        vals[i] = atoll(argv[i + 1]);
        if (!is_pow2(vals[i]) || vals[i] < 64 || SIG_BITS - ilog2(vals[i]) <= 0) {
            return 1;
        }
    }

    int64_t total = table_bits(vals[0]) + table_bits(vals[1]) + table_bits(vals[2]) + FIXED_BITS;
    printf("%lld\n", static_cast<long long>(total));
    return 0;
}

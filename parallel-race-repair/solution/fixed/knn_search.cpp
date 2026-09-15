
#include <iostream>
#include <vector>
#include <algorithm>
#include <numeric>
#include <cmath>
#include <cstdint>
#include <omp.h>

#ifdef SMALL_SIZE
static const int NDATA  = 200;
static const int NQUERY = 10;
#else
static const int NDATA  = 5000;
static const int NQUERY = 200;
#endif
static const int DIM = 16;
static const int K   = 5;

static uint32_t rng_next(uint32_t &s) {
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    return s;
}

static void make_dataset(std::vector<double> &data,
                         std::vector<double> &queries) {
    data.resize(NDATA * DIM);
    queries.resize(NQUERY * DIM);
    uint32_t s = 7;
    for (auto &v : data)    v = static_cast<double>(rng_next(s)) / 4294967295.0;
    for (auto &v : queries) v = static_cast<double>(rng_next(s)) / 4294967295.0;
}

static inline double sq_dist(const double *a, const double *b) {
    double s = 0.0;
    for (int d = 0; d < DIM; d++) {
        double diff = a[d] - b[d];
        s += diff * diff;
    }
    return s;
}

static void knn_sequential(const std::vector<double> &data,
                            const std::vector<double> &queries,
                            std::vector<int> &results) {
    results.resize(NQUERY * K);
    std::vector<double> dists(NDATA);
    std::vector<int> idx(NDATA);
    for (int q = 0; q < NQUERY; q++) {
        const double *qp = queries.data() + q * DIM;
        for (int i = 0; i < NDATA; i++) {
            dists[i] = sq_dist(data.data() + i * DIM, qp);
            idx[i] = i;
        }
        std::partial_sort(idx.begin(), idx.begin() + K, idx.end(),
                          [&](int a, int b) {
                              return dists[a] < dists[b] ||
                                     (dists[a] == dists[b] && a < b);
                          });
        for (int i = 0; i < K; i++)
            results[q * K + i] = idx[i];
    }
}

/* ---- FIXED ---- */
static void knn_parallel(const std::vector<double> &data,
                          const std::vector<double> &queries,
                          std::vector<int> &results) {
    results.resize(NQUERY * K);

    #pragma omp parallel
    {
        // Thread-private work buffers — each thread gets its own copy
        std::vector<double> dists(NDATA);
        std::vector<int> idx(NDATA);

        #pragma omp for schedule(dynamic)
        for (int q = 0; q < NQUERY; q++) {
            const double *qp = queries.data() + q * DIM;
            for (int i = 0; i < NDATA; i++) {
                dists[i] = sq_dist(data.data() + i * DIM, qp);
                idx[i] = i;
            }
            std::partial_sort(idx.begin(), idx.begin() + K, idx.end(),
                              [&](int a, int b) {
                                  return dists[a] < dists[b] ||
                                         (dists[a] == dists[b] && a < b);
                              });
            for (int i = 0; i < K; i++)
                results[q * K + i] = idx[i];
        }
    }
}

int main() {
    std::vector<double> data, queries;
    make_dataset(data, queries);

    std::vector<int> ref, par;

    double t0 = omp_get_wtime();
    knn_sequential(data, queries, ref);
    double t_seq = omp_get_wtime() - t0;

    t0 = omp_get_wtime();
    knn_parallel(data, queries, par);
    double t_par = omp_get_wtime() - t0;

    // Sort each query's K results by index for deterministic comparison
    for (int q = 0; q < NQUERY; q++) {
        std::sort(ref.begin() + q * K, ref.begin() + (q + 1) * K);
        std::sort(par.begin() + q * K, par.begin() + (q + 1) * K);
    }

    bool ok = (ref == par);
    std::cout << "RESULT: " << (ok ? "PASS" : "FAIL") << "\n";
    std::cout << "SEQ_TIME: " << t_seq << "\n";
    std::cout << "PAR_TIME: " << t_par << "\n";
    return ok ? 0 : 1;
}

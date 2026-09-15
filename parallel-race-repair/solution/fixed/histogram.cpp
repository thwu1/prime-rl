
#include <iostream>
#include <vector>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <omp.h>

#ifdef SMALL_SIZE
static const int N = 50000;
#else
static const int N = 2000000;
#endif
static const int NBINS = 256;

static uint32_t rng_next(uint32_t &s) {
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    return s;
}

static void generate_data(std::vector<double> &data) {
    data.resize(N);
    uint32_t s = 42;
    for (int i = 0; i < N; i++)
        data[i] = static_cast<double>(rng_next(s)) / 4294967295.0;
    // Plant exact 1.0 values to trigger boundary edge case
    data[N - 1] = 1.0;
    data[N - 2] = 1.0;
    data[N - 3] = 1.0;
}

static void hist_sequential(const std::vector<double> &data,
                            std::vector<long> &hist) {
    hist.assign(NBINS, 0);
    for (int i = 0; i < static_cast<int>(data.size()); i++) {
        int b = std::min(static_cast<int>(data[i] * NBINS), NBINS - 1);
        hist[b]++;
    }
}

/* ---- FIXED ---- */
static void hist_parallel(const std::vector<double> &data,
                          std::vector<long> &hist) {
    hist.assign(NBINS, 0);
    int n = static_cast<int>(data.size());
    int max_threads = omp_get_max_threads();

    // Flat array of per-thread histograms — avoids all synchronization
    std::vector<long> per_thread(max_threads * NBINS, 0);

    #pragma omp parallel
    {
        int tid = omp_get_thread_num();
        long *my_hist = per_thread.data() + tid * NBINS;

        #pragma omp for schedule(static)
        for (int i = 0; i < n; i++) {
            // Clamp bin index to [0, NBINS-1] to handle data[i] == 1.0
            int b = std::min(static_cast<int>(data[i] * NBINS), NBINS - 1);
            my_hist[b]++;
        }
    }

    // Serial merge of per-thread histograms — no races possible
    for (int t = 0; t < max_threads; t++)
        for (int b = 0; b < NBINS; b++)
            hist[b] += per_thread[t * NBINS + b];
}

int main() {
    std::vector<double> data;
    generate_data(data);

    std::vector<long> ref, par;

    double t0 = omp_get_wtime();
    hist_sequential(data, ref);
    double t_seq = omp_get_wtime() - t0;

    t0 = omp_get_wtime();
    hist_parallel(data, par);
    double t_par = omp_get_wtime() - t0;

    bool ok = (ref == par);
    std::cout << "RESULT: " << (ok ? "PASS" : "FAIL") << "\n";
    std::cout << "SEQ_TIME: " << t_seq << "\n";
    std::cout << "PAR_TIME: " << t_par << "\n";
    return ok ? 0 : 1;
}

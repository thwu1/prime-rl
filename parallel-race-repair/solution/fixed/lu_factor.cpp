
#include <iostream>
#include <vector>
#include <cmath>
#include <algorithm>
#include <numeric>
#include <cstdint>
#include <omp.h>

#ifdef SMALL_SIZE
static const int N = 128;
#else
static const int N = 512;
#endif

static uint32_t rng_next(uint32_t &s) {
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    return s;
}

static void make_matrix(std::vector<double> &A) {
    A.resize(static_cast<size_t>(N) * N);
    uint32_t s = 99;
    for (auto &v : A)
        v = static_cast<double>(rng_next(s)) / 4294967295.0 * 2.0 - 1.0;
}

static void lu_sequential(std::vector<double> &A, std::vector<int> &piv) {
    piv.resize(N);
    std::iota(piv.begin(), piv.end(), 0);

    for (int k = 0; k < N; k++) {
        // Find pivot row
        int maxrow = k;
        double maxval = std::abs(A[k * N + k]);
        for (int i = k + 1; i < N; i++) {
            double v = std::abs(A[i * N + k]);
            if (v > maxval) {
                maxval = v;
                maxrow = i;
            }
        }

        // Swap rows k and maxrow
        if (maxrow != k) {
            std::swap(piv[k], piv[maxrow]);
            for (int j = 0; j < N; j++)
                std::swap(A[k * N + j], A[maxrow * N + j]);
        }

        if (std::abs(A[k * N + k]) < 1e-15) continue;

        // Eliminate below pivot
        double pivot_inv = 1.0 / A[k * N + k];
        for (int i = k + 1; i < N; i++) {
            A[i * N + k] *= pivot_inv;
            for (int j = k + 1; j < N; j++)
                A[i * N + j] -= A[i * N + k] * A[k * N + j];
        }
    }
}

/* ---- FIXED ---- */
static void lu_parallel(std::vector<double> &A, std::vector<int> &piv) {
    piv.resize(N);
    std::iota(piv.begin(), piv.end(), 0);

    for (int k = 0; k < N; k++) {
        // Find pivot row — manual parallel reduction for argmax
        int maxrow = k;
        double maxval = std::abs(A[k * N + k]);

        #pragma omp parallel
        {
            int local_maxrow = k;
            double local_maxval = std::abs(A[k * N + k]);

            #pragma omp for nowait
            for (int i = k + 1; i < N; i++) {
                double v = std::abs(A[i * N + k]);
                if (v > local_maxval) {
                    local_maxval = v;
                    local_maxrow = i;
                }
            }

            #pragma omp critical
            {
                if (local_maxval > maxval) {
                    maxval = local_maxval;
                    maxrow = local_maxrow;
                }
            }
        }

        // Swap rows k and maxrow
        if (maxrow != k) {
            std::swap(piv[k], piv[maxrow]);
            for (int j = 0; j < N; j++)
                std::swap(A[k * N + j], A[maxrow * N + j]);
        }

        if (std::abs(A[k * N + k]) < 1e-15) continue;

        // Eliminate below pivot
        double pivot_inv = 1.0 / A[k * N + k];
        #pragma omp parallel for
        for (int i = k + 1; i < N; i++) {
            A[i * N + k] *= pivot_inv;
            for (int j = k + 1; j < N; j++)
                A[i * N + j] -= A[i * N + k] * A[k * N + j];
        }
    }
}

int main() {
    std::vector<double> A1, A2;
    make_matrix(A1);
    A2 = A1;

    std::vector<int> piv1, piv2;

    double t0 = omp_get_wtime();
    lu_sequential(A1, piv1);
    double t_seq = omp_get_wtime() - t0;

    t0 = omp_get_wtime();
    lu_parallel(A2, piv2);
    double t_par = omp_get_wtime() - t0;

    double maxdiff = 0.0;
    for (int i = 0; i < N * N; i++)
        maxdiff = std::max(maxdiff, std::abs(A1[i] - A2[i]));

    bool piv_ok = (piv1 == piv2);
    bool val_ok = (maxdiff < 1e-6);
    bool ok = piv_ok && val_ok;

    std::cout << "RESULT: " << (ok ? "PASS" : "FAIL") << "\n";
    std::cout << "MAX_DIFF: " << maxdiff << "\n";
    std::cout << "PIV_MATCH: " << (piv_ok ? "yes" : "no") << "\n";
    std::cout << "SEQ_TIME: " << t_seq << "\n";
    std::cout << "PAR_TIME: " << t_par << "\n";
    return ok ? 0 : 1;
}

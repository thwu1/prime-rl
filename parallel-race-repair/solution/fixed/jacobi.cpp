
#include <iostream>
#include <vector>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <omp.h>

#ifdef SMALL_SIZE
static const int NX = 64;
static const int NY = 64;
static const int NITER = 5;
#else
static const int NX = 256;
static const int NY = 256;
static const int NITER = 50;
#endif

static void init_grid(std::vector<double> &u) {
    u.assign(NX * NY, 0.0);
    // Top boundary = 100
    for (int j = 0; j < NY; j++)
        u[j] = 100.0;
    // Left boundary = linearly decreasing from 75 to 0
    for (int i = 0; i < NX; i++)
        u[i * NY] = 75.0 * (1.0 - static_cast<double>(i) / (NX - 1));
    // Internal heat sources
    if (NX > 4 && NY > 4) {
        u[(NX / 3) * NY + NY / 3] = 500.0;
        u[(2 * NX / 3) * NY + 2 * NY / 3] = 500.0;
    }
}

static double jacobi_sequential(std::vector<double> u) {
    std::vector<double> u_new(u);
    for (int iter = 0; iter < NITER; iter++) {
        for (int i = 1; i < NX - 1; i++)
            for (int j = 1; j < NY - 1; j++)
                u_new[i * NY + j] = 0.25 * (u[(i - 1) * NY + j] +
                                             u[(i + 1) * NY + j] +
                                             u[i * NY + j - 1] +
                                             u[i * NY + j + 1]);
        u.swap(u_new);
    }
    double sum = 0.0;
    for (auto v : u) sum += v;
    return sum;
}

/* ---- FIXED ---- */
static double jacobi_parallel(std::vector<double> u) {
    int n = NX * NY;
    // Allocate a second buffer for double-buffered Jacobi iteration
    std::vector<double> u_new(u);

    for (int iter = 0; iter < NITER; iter++) {
        #pragma omp parallel for collapse(2)
        for (int i = 1; i < NX - 1; i++)
            for (int j = 1; j < NY - 1; j++)
                u_new[i * NY + j] = 0.25 * (u[(i - 1) * NY + j] +
                                              u[(i + 1) * NY + j] +
                                              u[i * NY + j - 1] +
                                              u[i * NY + j + 1]);
        u.swap(u_new);
    }

    // Use reduction clause to safely accumulate the sum
    double sum = 0.0;
    #pragma omp parallel for reduction(+:sum)
    for (int i = 0; i < n; i++)
        sum += u[i];

    return sum;
}

int main() {
    std::vector<double> grid;
    init_grid(grid);

    double t0 = omp_get_wtime();
    double ref = jacobi_sequential(grid);
    double t_seq = omp_get_wtime() - t0;

    t0 = omp_get_wtime();
    double par = jacobi_parallel(grid);
    double t_par = omp_get_wtime() - t0;

    double diff = std::abs(ref - par);
    bool ok = diff < 1e-6;

    std::cout << "RESULT: " << (ok ? "PASS" : "FAIL") << "\n";
    std::cout << "REF_SUM: " << ref << "\n";
    std::cout << "PAR_SUM: " << par << "\n";
    std::cout << "DIFF: " << diff << "\n";
    std::cout << "SEQ_TIME: " << t_seq << "\n";
    std::cout << "PAR_TIME: " << t_par << "\n";
    return ok ? 0 : 1;
}

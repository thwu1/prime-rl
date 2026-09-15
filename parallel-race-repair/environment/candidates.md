# Candidate Parallelization Strategies

Evaluate each candidate for correctness and race-freedom under multi-threaded OpenMP execution.

---

## histogram.cpp

### Strategy A
Atomic increments on shared histogram bins:
```cpp
static void hist_parallel(const std::vector<double> &data,
                          std::vector<long> &hist) {
    hist.assign(NBINS, 0);
    int n = static_cast<int>(data.size());
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < n; i++) {
        int b = static_cast<int>(data[i] * NBINS);
        #pragma omp atomic
        hist[b]++;
    }
}
```

### Strategy B
Critical section with clamped bin index:
```cpp
static void hist_parallel(const std::vector<double> &data,
                          std::vector<long> &hist) {
    hist.assign(NBINS, 0);
    int n = static_cast<int>(data.size());
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < n; i++) {
        int b = std::min(static_cast<int>(data[i] * NBINS), NBINS - 1);
        #pragma omp critical
        { hist[b]++; }
    }
}
```

### Strategy C
Per-thread histogram copies merged after parallel region:
```cpp
static void hist_parallel(const std::vector<double> &data,
                          std::vector<long> &hist) {
    hist.assign(NBINS, 0);
    int n = static_cast<int>(data.size());
    int nthreads = omp_get_max_threads();
    std::vector<long> per_thread(nthreads * NBINS, 0);
    #pragma omp parallel
    {
        int tid = omp_get_thread_num();
        long *my = per_thread.data() + tid * NBINS;
        #pragma omp for schedule(static)
        for (int i = 0; i < n; i++) {
            int b = static_cast<int>(data[i] * NBINS);
            my[b]++;
        }
    }
    for (int t = 0; t < nthreads; t++)
        for (int b = 0; b < NBINS; b++)
            hist[b] += per_thread[t * NBINS + b];
}
```

---

## jacobi.cpp

### Strategy A
In-place parallel stencil update with correct sum reduction:
```cpp
static double jacobi_parallel(std::vector<double> u) {
    int n = NX * NY;
    for (int iter = 0; iter < NITER; iter++) {
        #pragma omp parallel for collapse(2)
        for (int i = 1; i < NX - 1; i++)
            for (int j = 1; j < NY - 1; j++)
                u[i * NY + j] = 0.25 * (u[(i-1)*NY+j] + u[(i+1)*NY+j] +
                                         u[i*NY+j-1] + u[i*NY+j+1]);
    }
    double sum = 0.0;
    #pragma omp parallel for reduction(+:sum)
    for (int i = 0; i < n; i++) sum += u[i];
    return sum;
}
```

### Strategy B
Double-buffered iteration but unprotected sum accumulation:
```cpp
static double jacobi_parallel(std::vector<double> u) {
    int n = NX * NY;
    std::vector<double> u_new(u);
    for (int iter = 0; iter < NITER; iter++) {
        #pragma omp parallel for collapse(2)
        for (int i = 1; i < NX - 1; i++)
            for (int j = 1; j < NY - 1; j++)
                u_new[i * NY + j] = 0.25 * (u[(i-1)*NY+j] + u[(i+1)*NY+j] +
                                              u[i*NY+j-1] + u[i*NY+j+1]);
        u.swap(u_new);
    }
    double sum = 0.0;
    #pragma omp parallel for
    for (int i = 0; i < n; i++) sum += u[i];
    return sum;
}
```

### Strategy C
Double-buffered iteration with reduction on sum:
```cpp
static double jacobi_parallel(std::vector<double> u) {
    int n = NX * NY;
    std::vector<double> u_new(u);
    for (int iter = 0; iter < NITER; iter++) {
        #pragma omp parallel for collapse(2)
        for (int i = 1; i < NX - 1; i++)
            for (int j = 1; j < NY - 1; j++)
                u_new[i * NY + j] = 0.25 * (u[(i-1)*NY+j] + u[(i+1)*NY+j] +
                                              u[i*NY+j-1] + u[i*NY+j+1]);
        u.swap(u_new);
    }
    double sum = 0.0;
    #pragma omp parallel for reduction(+:sum)
    for (int i = 0; i < n; i++) sum += u[i];
    return sum;
}
```

---

## knn_search.cpp

### Strategy A
Shared work buffers with dynamic scheduling:
```cpp
static void knn_parallel(const std::vector<double> &data,
                          const std::vector<double> &queries,
                          std::vector<int> &results) {
    results.resize(NQUERY * K);
    std::vector<double> dists(NDATA);
    std::vector<int> idx(NDATA);
    #pragma omp parallel for schedule(dynamic)
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
```

### Strategy B
Private clause on work buffers:
```cpp
static void knn_parallel(const std::vector<double> &data,
                          const std::vector<double> &queries,
                          std::vector<int> &results) {
    results.resize(NQUERY * K);
    std::vector<double> dists(NDATA);
    std::vector<int> idx(NDATA);
    #pragma omp parallel for schedule(dynamic) private(dists, idx)
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
```

### Strategy C
Thread-local buffer declarations inside parallel region:
```cpp
static void knn_parallel(const std::vector<double> &data,
                          const std::vector<double> &queries,
                          std::vector<int> &results) {
    results.resize(NQUERY * K);
    #pragma omp parallel
    {
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
```

---

## lu_factor.cpp

All three strategies parallelize the elimination step identically (which is correct). They differ in how they parallelize the pivot search (argmax).

### Strategy A
Naive parallel pivot search with shared variables:
```cpp
static void lu_parallel(std::vector<double> &A, std::vector<int> &piv) {
    piv.resize(N);
    std::iota(piv.begin(), piv.end(), 0);
    for (int k = 0; k < N; k++) {
        int maxrow = k;
        double maxval = std::abs(A[k * N + k]);
        #pragma omp parallel for
        for (int i = k + 1; i < N; i++) {
            double v = std::abs(A[i * N + k]);
            if (v > maxval) { maxval = v; maxrow = i; }
        }
        if (maxrow != k) {
            std::swap(piv[k], piv[maxrow]);
            for (int j = 0; j < N; j++)
                std::swap(A[k * N + j], A[maxrow * N + j]);
        }
        if (std::abs(A[k * N + k]) < 1e-15) continue;
        double pivot_inv = 1.0 / A[k * N + k];
        #pragma omp parallel for
        for (int i = k + 1; i < N; i++) {
            A[i * N + k] *= pivot_inv;
            for (int j = k + 1; j < N; j++)
                A[i * N + j] -= A[i * N + k] * A[k * N + j];
        }
    }
}
```

### Strategy B
Reduction on max value but shared row index:
```cpp
static void lu_parallel(std::vector<double> &A, std::vector<int> &piv) {
    piv.resize(N);
    std::iota(piv.begin(), piv.end(), 0);
    for (int k = 0; k < N; k++) {
        int maxrow = k;
        double maxval = std::abs(A[k * N + k]);
        #pragma omp parallel for reduction(max:maxval)
        for (int i = k + 1; i < N; i++) {
            double v = std::abs(A[i * N + k]);
            if (v > maxval) { maxval = v; maxrow = i; }
        }
        if (maxrow != k) {
            std::swap(piv[k], piv[maxrow]);
            for (int j = 0; j < N; j++)
                std::swap(A[k * N + j], A[maxrow * N + j]);
        }
        if (std::abs(A[k * N + k]) < 1e-15) continue;
        double pivot_inv = 1.0 / A[k * N + k];
        #pragma omp parallel for
        for (int i = k + 1; i < N; i++) {
            A[i * N + k] *= pivot_inv;
            for (int j = k + 1; j < N; j++)
                A[i * N + j] -= A[i * N + k] * A[k * N + j];
        }
    }
}
```

### Strategy C
Manual parallel reduction with thread-local variables and critical merge:
```cpp
static void lu_parallel(std::vector<double> &A, std::vector<int> &piv) {
    piv.resize(N);
    std::iota(piv.begin(), piv.end(), 0);
    for (int k = 0; k < N; k++) {
        int maxrow = k;
        double maxval = std::abs(A[k * N + k]);
        #pragma omp parallel
        {
            int local_maxrow = k;
            double local_maxval = std::abs(A[k * N + k]);
            #pragma omp for nowait
            for (int i = k + 1; i < N; i++) {
                double v = std::abs(A[i * N + k]);
                if (v > local_maxval) { local_maxval = v; local_maxrow = i; }
            }
            #pragma omp critical
            {
                if (local_maxval > maxval) { maxval = local_maxval; maxrow = local_maxrow; }
            }
        }
        if (maxrow != k) {
            std::swap(piv[k], piv[maxrow]);
            for (int j = 0; j < N; j++)
                std::swap(A[k * N + j], A[maxrow * N + j]);
        }
        if (std::abs(A[k * N + k]) < 1e-15) continue;
        double pivot_inv = 1.0 / A[k * N + k];
        #pragma omp parallel for
        for (int i = k + 1; i < N; i++) {
            A[i * N + k] *= pivot_inv;
            for (int j = k + 1; j < N; j++)
                A[i * N + j] -= A[i * N + k] * A[k * N + j];
        }
    }
}
```

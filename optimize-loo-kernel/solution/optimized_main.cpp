//
// Optimized analytics tool.
// LOO cross-validation: O(N*P^2 + P^3) via PRESS / hat-matrix formula.
// Kernel sum:           O(N) via suffix-sum reduction.

#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <cmath>
#include <chrono>
#include <algorithm>
#include <iomanip>
#include <cstring>
#include <cstdlib>

static constexpr int P = 5;
static constexpr double LAMBDA = 0.01;
static constexpr double ALPHA = 0.5;

struct DataPoint {
    double features[P];
    double timestamp;
    double weight;
    double target;
};

static std::vector<DataPoint> read_data(const std::string& path) {
    std::vector<DataPoint> data;
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "Error: cannot open " << path << std::endl;
        return data;
    }

    std::string line;
    if (!std::getline(file, line)) return data;   // skip header

    while (std::getline(file, line)) {
        if (line.empty()) continue;
        DataPoint dp;
        std::istringstream iss(line);
        std::string token;
        for (int j = 0; j < P; j++) {
            if (!std::getline(iss, token, ',')) break;
            dp.features[j] = std::stod(token);
        }
        if (std::getline(iss, token, ',')) dp.timestamp = std::stod(token);
        if (std::getline(iss, token, ',')) dp.weight = std::stod(token);
        if (std::getline(iss, token, ',')) dp.target = std::stod(token);
        data.push_back(dp);
    }
    return data;
}

// ── Matrix inversion (Gauss-Jordan with partial pivoting, P x P) ──────────
static void invert_matrix(const double src[P][P], double dst[P][P]) {
    double aug[P][2 * P];
    for (int i = 0; i < P; i++) {
        for (int j = 0; j < P; j++) {
            aug[i][j] = src[i][j];
            aug[i][P + j] = (i == j) ? 1.0 : 0.0;
        }
    }
    for (int col = 0; col < P; col++) {
        int pivot_row = col;
        for (int row = col + 1; row < P; row++)
            if (std::fabs(aug[row][col]) > std::fabs(aug[pivot_row][col]))
                pivot_row = row;
        if (pivot_row != col)
            for (int j = 0; j < 2 * P; j++)
                std::swap(aug[col][j], aug[pivot_row][j]);

        double pivot = aug[col][col];
        for (int j = 0; j < 2 * P; j++) aug[col][j] /= pivot;

        for (int row = 0; row < P; row++) {
            if (row == col) continue;
            double factor = aug[row][col];
            for (int j = 0; j < 2 * P; j++)
                aug[row][j] -= factor * aug[col][j];
        }
    }
    for (int i = 0; i < P; i++)
        for (int j = 0; j < P; j++)
            dst[i][j] = aug[i][P + j];
}

// ── Optimized LOO: PRESS residual formula ─────────────────────────────────
static void compute_loo(const std::vector<DataPoint>& data, double lambda,
                        double& rmse, double& mae) {
    const int N = static_cast<int>(data.size());

    double XtX[P][P] = {};
    double Xty[P] = {};
    for (int k = 0; k < N; k++) {
        const double* x = data[k].features;
        double yk = data[k].target;
        for (int a = 0; a < P; a++) {
            for (int b = 0; b <= a; b++)
                XtX[a][b] += x[a] * x[b];
            Xty[a] += x[a] * yk;
        }
    }
    for (int a = 0; a < P; a++)
        for (int b = a + 1; b < P; b++)
            XtX[a][b] = XtX[b][a];

    for (int a = 0; a < P; a++) XtX[a][a] += lambda;

    double Ainv[P][P];
    invert_matrix(XtX, Ainv);

    double beta[P] = {};
    for (int a = 0; a < P; a++)
        for (int b = 0; b < P; b++)
            beta[a] += Ainv[a][b] * Xty[b];

    double sum_sq = 0.0, sum_abs = 0.0;
    for (int i = 0; i < N; i++) {
        const double* x = data[i].features;

        double y_hat = 0.0;
        for (int a = 0; a < P; a++) y_hat += x[a] * beta[a];
        double e_i = data[i].target - y_hat;

        double z[P] = {};
        for (int a = 0; a < P; a++)
            for (int b = 0; b < P; b++)
                z[a] += Ainv[a][b] * x[b];

        double h_ii = 0.0;
        for (int a = 0; a < P; a++) h_ii += x[a] * z[a];

        double loo_e = e_i / (1.0 - h_ii);
        sum_sq += loo_e * loo_e;
        sum_abs += std::fabs(loo_e);
    }

    rmse = std::sqrt(sum_sq / N);
    mae = sum_abs / N;
}

// ── Optimized kernel sum via suffix-sum reduction ─────────────────────────
static double compute_kernel_sum(const std::vector<DataPoint>& data,
                                 double alpha) {
    const int N = static_cast<int>(data.size());

    double suffix_w = 0.0;
    double S = 0.0;
    for (int k = N - 1; k >= 0; k--) {
        double gk = std::exp(-alpha * data[k].timestamp);
        double wk = data[k].weight;
        S += gk * wk * (2.0 * suffix_w + wk);
        suffix_w += wk;
    }
    return S;
}

int main() {
    const std::string input_path = "/app/data/input.csv";
    const std::string output_path = "/app/output/results.json";

    auto data = read_data(input_path);
    if (data.empty()) {
        std::cerr << "No data loaded." << std::endl;
        return 1;
    }
    std::cerr << "Loaded " << data.size() << " records." << std::endl;

    auto t0 = std::chrono::high_resolution_clock::now();

    double rmse = 0.0, mae = 0.0;
    compute_loo(data, LAMBDA, rmse, mae);

    double kernel_sum = compute_kernel_sum(data, ALPHA);

    auto t1 = std::chrono::high_resolution_clock::now();
    double elapsed = std::chrono::duration<double>(t1 - t0).count();
    std::cerr << "Computation time: " << elapsed << " seconds" << std::endl;

    std::system("mkdir -p /app/output");

    std::ofstream out(output_path);
    out << std::setprecision(15) << std::scientific;
    out << "{\n";
    out << "  \"loo_rmse\": " << rmse << ",\n";
    out << "  \"loo_mae\": " << mae << ",\n";
    out << "  \"kernel_sum\": " << kernel_sum << ",\n";
    out << "  \"elapsed_sec\": " << elapsed << "\n";
    out << "}\n";

    std::cerr << "Results written to " << output_path << std::endl;
    return 0;
}

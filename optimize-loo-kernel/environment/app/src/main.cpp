
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
    // Skip header line
    if (!std::getline(file, line)) return data;

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

// Solve a PxP linear system Ax = b using Gaussian elimination with partial pivoting.
// The arrays A and b are modified in place. Solution is written to x.
static void solve_system(double A[P][P], double b[P], double x[P]) {
    double aug[P][P + 1];
    for (int i = 0; i < P; i++) {
        for (int j = 0; j < P; j++) aug[i][j] = A[i][j];
        aug[i][P] = b[i];
    }

    for (int col = 0; col < P; col++) {
        // Partial pivoting
        int pivot_row = col;
        for (int row = col + 1; row < P; row++) {
            if (std::fabs(aug[row][col]) > std::fabs(aug[pivot_row][col]))
                pivot_row = row;
        }
        if (pivot_row != col) {
            for (int j = 0; j <= P; j++)
                std::swap(aug[col][j], aug[pivot_row][j]);
        }

        double pivot = aug[col][col];
        if (std::fabs(pivot) < 1e-15) continue;
        for (int j = col; j <= P; j++) aug[col][j] /= pivot;

        for (int row = 0; row < P; row++) {
            if (row == col) continue;
            double factor = aug[row][col];
            for (int j = col; j <= P; j++)
                aug[row][j] -= factor * aug[col][j];
        }
    }

    for (int i = 0; i < P; i++) x[i] = aug[i][P];
}

// Leave-One-Out cross-validation for ridge regression.
// Naive O(N^2 * P^2) implementation: for each held-out point i,
// recompute X^T X and X^T y from scratch over all N-1 remaining points,
// solve the P x P system, and predict y_hat_i.
static void compute_loo(const std::vector<DataPoint>& data, double lambda,
                        double& rmse, double& mae) {
    const int N = static_cast<int>(data.size());
    double sum_sq_err = 0.0;
    double sum_abs_err = 0.0;

    for (int i = 0; i < N; i++) {
        // Build X^T X and X^T y excluding point i
        double XtX[P][P] = {};
        double Xty[P] = {};

        for (int k = 0; k < N; k++) {
            if (k == i) continue;
            const double* xk = data[k].features;
            double yk = data[k].target;
            for (int a = 0; a < P; a++) {
                for (int b = 0; b < P; b++) {
                    XtX[a][b] += xk[a] * xk[b];
                }
                Xty[a] += xk[a] * yk;
            }
        }

        // Add ridge regularization
        for (int a = 0; a < P; a++) XtX[a][a] += lambda;

        // Solve for regression coefficients
        double beta[P];
        solve_system(XtX, Xty, beta);

        // Compute prediction and error for held-out point
        double y_hat = 0.0;
        for (int a = 0; a < P; a++)
            y_hat += data[i].features[a] * beta[a];
        double err = data[i].target - y_hat;

        sum_sq_err += err * err;
        sum_abs_err += std::fabs(err);
    }

    rmse = std::sqrt(sum_sq_err / N);
    mae = sum_abs_err / N;
}

// Pairwise kernel sum: S = sum_i sum_j g(min(t_i, t_j)) * w_i * w_j
// where g(t) = exp(-alpha * t).
// Naive O(N^2) implementation with two nested loops.
static double compute_kernel_sum(const std::vector<DataPoint>& data, double alpha) {
    const int N = static_cast<int>(data.size());
    double S = 0.0;
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++) {
            double t_min = std::min(data[i].timestamp, data[j].timestamp);
            S += std::exp(-alpha * t_min) * data[i].weight * data[j].weight;
        }
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

    // Ensure output directory exists
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

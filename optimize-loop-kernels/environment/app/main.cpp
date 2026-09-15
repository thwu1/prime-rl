#include <iostream>
#include <vector>
#include <cmath>
#include <iomanip>
#include <cstddef>

// Kernel declarations
void scale_array(float* out, const float* in, float* coeff, size_t n);
void column_sums(const double* matrix, double* sums, int rows, int cols);
double dot_product(const double* a, const double* b, size_t n);
void apply_transform(double* out, const double* in, size_t n);

static bool approx_equal_rel(double a, double b, double rel_tol) {
    if (a == b) return true;
    double denom = std::max(std::fabs(a), std::fabs(b));
    if (denom < 1e-15) return std::fabs(a - b) < 1e-15;
    return std::fabs(a - b) / denom < rel_tol;
}

int main() {
    bool all_pass = true;

    // Test 1: scale_array
    {
        const size_t n = 10000;
        std::vector<float> in(n), out(n);
        float coeff = 3.14159f;
        for (size_t i = 0; i < n; i++) {
            in[i] = static_cast<float>(i) * 0.01f - 50.0f;
        }
        scale_array(out.data(), in.data(), &coeff, n);

        bool pass = true;
        for (size_t i = 0; i < n; i++) {
            float expected = in[i] * 3.14159f;
            if (std::fabs(out[i] - expected) > 1e-3f) {
                pass = false;
                std::cerr << "scale_array mismatch at i=" << i
                          << " got=" << out[i] << " expected=" << expected << std::endl;
                break;
            }
        }
        std::cout << "scale_array: " << (pass ? "PASS" : "FAIL") << std::endl;
        if (!pass) all_pass = false;
    }

    // Test 2: column_sums
    {
        const int rows = 500, cols = 300;
        std::vector<double> matrix(rows * cols), sums(cols);
        for (int i = 0; i < rows; i++) {
            for (int j = 0; j < cols; j++) {
                matrix[i * cols + j] = static_cast<double>((i + 1) * (j + 1)) * 0.0001;
            }
        }
        column_sums(matrix.data(), sums.data(), rows, cols);

        bool pass = true;
        for (int j = 0; j < cols; j++) {
            double expected = 0.0;
            for (int i = 0; i < rows; i++) {
                expected += static_cast<double>((i + 1) * (j + 1)) * 0.0001;
            }
            if (!approx_equal_rel(sums[j], expected, 1e-9)) {
                pass = false;
                std::cerr << "column_sums mismatch at j=" << j
                          << " got=" << sums[j] << " expected=" << expected << std::endl;
                break;
            }
        }
        std::cout << "column_sums: " << (pass ? "PASS" : "FAIL") << std::endl;
        if (!pass) all_pass = false;
    }

    // Test 3: dot_product
    {
        const size_t n = 100000;
        std::vector<double> a(n), b(n);
        for (size_t i = 0; i < n; i++) {
            a[i] = static_cast<double>(i + 1) * 0.001;
            b[i] = static_cast<double>(n - i) * 0.001;
        }
        double result = dot_product(a.data(), b.data(), n);

        double expected = 0.0;
        for (size_t i = 0; i < n; i++) {
            expected += a[i] * b[i];
        }

        bool pass = approx_equal_rel(result, expected, 1e-8);
        std::cout << "dot_product: " << (pass ? "PASS" : "FAIL") << std::endl;
        std::cout << "dot_product_value: " << std::setprecision(15) << result << std::endl;
        if (!pass) all_pass = false;
    }

    // Test 4: apply_transform
    {
        const size_t n = 10000;
        std::vector<double> in(n), out(n);
        for (size_t i = 0; i < n; i++) {
            in[i] = static_cast<double>(i) * 0.1 - 500.0;
        }
        apply_transform(out.data(), in.data(), n);

        bool pass = true;
        for (size_t i = 0; i < n; i++) {
            double x = in[i];
            double expected = x * x + 2.0 * x + 1.0;
            if (!approx_equal_rel(out[i], expected, 1e-12)) {
                pass = false;
                std::cerr << "apply_transform mismatch at i=" << i
                          << " got=" << out[i] << " expected=" << expected << std::endl;
                break;
            }
        }
        std::cout << "apply_transform: " << (pass ? "PASS" : "FAIL") << std::endl;
        if (!pass) all_pass = false;
    }

    return all_pass ? 0 : 1;
}

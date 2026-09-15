#include <cstddef>
#include <cmath>

// Kernel 1: scale_array
// Scales every element of 'in' by a coefficient and writes to 'out'
void scale_array(float* out, const float* in, float* coeff, size_t n) {
    for (size_t i = 0; i < n; i++) {
        out[i] = in[i] * (*coeff);
    }
}

// Kernel 2: column_sums
// Computes column-wise sums of a row-major matrix
void column_sums(const double* matrix, double* sums, int rows, int cols) {
    for (int j = 0; j < cols; j++) {
        sums[j] = 0.0;
        for (int i = 0; i < rows; i++) {
            sums[j] += matrix[i * cols + j];
        }
    }
}

// Kernel 3: dot_product
// Computes the dot product of two double arrays
double dot_product(const double* a, const double* b, size_t n) {
    double sum = 0.0;
    for (size_t i = 0; i < n; i++) {
        sum += a[i] * b[i];
    }
    return sum;
}

// Kernel 4: apply_transform
// Applies a transformation function to each element
extern double my_transform(double x);

void apply_transform(double* out, const double* in, size_t n) {
    for (size_t i = 0; i < n; i++) {
        out[i] = my_transform(in[i]);
    }
}

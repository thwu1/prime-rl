/* Benchmark: loop-centric optimizations (LICM, strength reduction, unrolling) */

void matrix_multiply(int *A, int *B, int *C, int n) {
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            int sum = 0;
            for (int k = 0; k < n; k++) {
                sum += A[i * n + k] * B[k * n + j];
            }
            C[i * n + j] = sum;
        }
    }
}

void convolution_1d(const float *input, float *output,
                    const float *kernel, int in_len, int k_len) {
    for (int i = 0; i < in_len; i++) {
        float acc = 0.0f;
        for (int j = 0; j < k_len; j++) {
            int idx = i - k_len / 2 + j;
            if (idx >= 0 && idx < in_len) {
                acc += kernel[j] * input[idx];
            }
        }
        output[i] = acc;
    }
}

void prefix_sum(int *arr, int n) {
    for (int i = 1; i < n; i++) {
        arr[i] += arr[i - 1];
    }
}

int find_max_subarray(int *arr, int n) {
    int max_sum = arr[0];
    int current = arr[0];
    for (int i = 1; i < n; i++) {
        if (current + arr[i] > arr[i])
            current = current + arr[i];
        else
            current = arr[i];
        if (current > max_sum)
            max_sum = current;
    }
    return max_sum;
}

void transpose(int *matrix, int *result, int rows, int cols) {
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            result[j * rows + i] = matrix[i * cols + j];
        }
    }
}

void saxpy(float *y, const float *x, float a, int n) {
    for (int i = 0; i < n; i++) {
        y[i] = a * x[i] + y[i];
    }
}

int dot_product(const int *a, const int *b, int n) {
    int result = 0;
    for (int i = 0; i < n; i++) {
        result += a[i] * b[i];
    }
    return result;
}

void normalize(float *data, int n) {
    float sum = 0.0f;
    for (int i = 0; i < n; i++) sum += data[i];
    float mean = sum / n;
    float var = 0.0f;
    for (int i = 0; i < n; i++) {
        float diff = data[i] - mean;
        var += diff * diff;
    }
    var = var / n;
    for (int i = 0; i < n; i++) {
        data[i] = (data[i] - mean);
    }
}

#include <stdint.h>

/* Function 1: Integer division by constant */
uint32_t divide_by_7(uint32_t x) {
    return x / 7;
}

/* Function 2: Integer modulo by constant */
uint32_t modulo_13(uint32_t x) {
    return x % 13;
}

/* Function 3: Pointer aliasing blocks register promotion */
void accumulate(int *total, const int *data, int n) {
    for (int i = 0; i < n; i++) {
        *total += data[i];
    }
}

/* Function 4: Loop induction variable */
void fill_multiples(int factor, int *output, int n) {
    for (int i = 0; i < n; i++) {
        output[i] = factor * i;
    }
}

/* Function 5: Floating-point reduction loop */
float sum_floats(const float *arr, int n) {
    float total = 0.0f;
    for (int i = 0; i < n; i++) {
        total += arr[i];
    }
    return total;
}

/* Function 6: Dense switch with non-arithmetic return values */
int categorize(int x) {
    switch(x) {
        case 0: return 42;
        case 1: return 17;
        case 2: return -8;
        case 3: return 255;
        case 4: return 0;
        case 5: return 99;
        case 6: return -42;
        case 7: return 1;
        default: return -1;
    }
}

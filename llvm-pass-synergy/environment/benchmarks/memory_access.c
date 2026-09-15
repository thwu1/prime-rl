/* Benchmark: memory access patterns, dead stores, load elimination */

void copy_and_transform(int *dst, const int *src, int n, int offset) {
    /* Redundant loads: src[i] loaded multiple times */
    for (int i = 0; i < n; i++) {
        int v = src[i];
        dst[i] = v + offset;
        int v2 = src[i];  /* Redundant load */
        dst[i] = v2 + offset + 1;  /* Dead store above */
    }
}

void fill_pattern(int *arr, int n) {
    /* First fill is dead if immediately overwritten */
    for (int i = 0; i < n; i++) arr[i] = 0;
    for (int i = 0; i < n; i++) arr[i] = i * i;
}

void swap_arrays(int *a, int *b, int n) {
    for (int i = 0; i < n; i++) {
        int tmp = a[i];
        a[i] = b[i];
        b[i] = tmp;
    }
}

void scatter_gather(int *dst, const int *src, const int *indices, int n) {
    for (int i = 0; i < n; i++) {
        dst[i] = src[indices[i]];
    }
}

int count_nonzero(const int *arr, int n) {
    int count = 0;
    for (int i = 0; i < n; i++) {
        if (arr[i] != 0) count++;
    }
    return count;
}

void compact(const int *src, int *dst, int n, int *out_len) {
    int j = 0;
    for (int i = 0; i < n; i++) {
        if (src[i] != 0) {
            dst[j++] = src[i];
        }
    }
    *out_len = j;
}

void merge_sorted(const int *a, int na, const int *b, int nb, int *out) {
    int i = 0, j = 0, k = 0;
    while (i < na && j < nb) {
        if (a[i] <= b[j]) {
            out[k++] = a[i++];
        } else {
            out[k++] = b[j++];
        }
    }
    while (i < na) out[k++] = a[i++];
    while (j < nb) out[k++] = b[j++];
}

void reverse_array(int *arr, int n) {
    for (int i = 0; i < n / 2; i++) {
        int tmp = arr[i];
        arr[i] = arr[n - 1 - i];
        arr[n - 1 - i] = tmp;
    }
}

void add_arrays_with_dead_store(int *c, const int *a, const int *b, int n) {
    for (int i = 0; i < n; i++) {
        c[i] = a[i] - b[i];   /* Will be overwritten */
        c[i] = a[i] + b[i];   /* Dead store above */
    }
}

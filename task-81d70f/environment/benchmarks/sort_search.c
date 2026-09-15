/* Sorting and searching with helper functions */

static void swap(int *a, int *b) {
    int t = *a;
    *a = *b;
    *b = t;
}

static int median_of_three(int *arr, int a, int b, int c) {
    if (arr[a] > arr[b]) swap(&arr[a], &arr[b]);
    if (arr[b] > arr[c]) swap(&arr[b], &arr[c]);
    if (arr[a] > arr[b]) swap(&arr[a], &arr[b]);
    return b;
}

int partition(int *arr, int low, int high) {
    int mid = low + (high - low) / 2;
    int pivot_idx = median_of_three(arr, low, mid, high);
    int pivot = arr[pivot_idx];
    swap(&arr[pivot_idx], &arr[high]);
    int i = low - 1;
    for (int j = low; j < high; j++) {
        if (arr[j] <= pivot) {
            i++;
            swap(&arr[i], &arr[j]);
        }
    }
    swap(&arr[i + 1], &arr[high]);
    return i + 1;
}

void quicksort(int *arr, int low, int high) {
    while (low < high) {
        int pi = partition(arr, low, high);
        if (pi - low < high - pi) {
            quicksort(arr, low, pi - 1);
            low = pi + 1;
        } else {
            quicksort(arr, pi + 1, high);
            high = pi - 1;
        }
    }
}

int binary_search(int *arr, int n, int target) {
    int lo = 0, hi = n - 1;
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] == target) return mid;
        if (arr[mid] < target) lo = mid + 1;
        else hi = mid - 1;
    }
    return -1;
}

int interpolation_search(int *arr, int n, int target) {
    int lo = 0, hi = n - 1;
    while (lo <= hi && target >= arr[lo] && target <= arr[hi]) {
        if (lo == hi) {
            if (arr[lo] == target) return lo;
            return -1;
        }
        int pos = lo + ((long long)(target - arr[lo]) * (hi - lo)) / (arr[hi] - arr[lo]);
        if (pos < lo || pos > hi) return -1;
        if (arr[pos] == target) return pos;
        if (arr[pos] < target) lo = pos + 1;
        else hi = pos - 1;
    }
    return -1;
}

void insertion_sort(int *arr, int n) {
    for (int i = 1; i < n; i++) {
        int key = arr[i];
        int j = i - 1;
        while (j >= 0 && arr[j] > key) {
            arr[j + 1] = arr[j];
            j--;
        }
        arr[j + 1] = key;
    }
}

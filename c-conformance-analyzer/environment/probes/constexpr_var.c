/* Probe: constexpr for compile-time constant variables (C23 feature) */
int main(void) {
    constexpr int N = 42;
    int arr[N];
    return (sizeof(arr) / sizeof(arr[0]) == 42) ? 0 : 1;
}

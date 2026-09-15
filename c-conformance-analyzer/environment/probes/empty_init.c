/* Probe: empty initializer braces {} for zero-initialization (C23 feature) */
int main(void) {
    int arr[5] = {};
    int sum = 0;
    for (int i = 0; i < 5; i++) sum += arr[i];
    return (sum == 0) ? 0 : 1;
}

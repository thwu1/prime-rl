void bubble_sort(int *arr, int n) {
    for (int i = 0; i < n - 1; i++) {
        int swapped = 0;
        for (int j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int tmp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = tmp;
                swapped = 1;
            }
        }
        if (!swapped)
            break;
    }
}

int main(void) {
    int arr[100];
    for (int i = 0; i < 100; i++)
        arr[i] = (100 - i) * 3 + i % 7;
    bubble_sort(arr, 100);
    return arr[0] + arr[99];
}

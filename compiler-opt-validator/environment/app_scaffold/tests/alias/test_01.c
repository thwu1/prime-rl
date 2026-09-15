#include <stdio.h>

/* Test: pointer aliasing — verify compiler handles aliased
   and non-aliased pointer accesses correctly */
void add_arrays(int * restrict a, int * restrict b, int * restrict c, int n) {
    for (int i = 0; i < n; i++)
        c[i] = a[i] + b[i];
}

void add_aliased(int *a, int *b, int *c, int n) {
    for (int i = 0; i < n; i++)
        c[i] = a[i] + b[i];
}

int main(void) {
    int arr[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    int out[4];

    /* Non-aliasing case with restrict */
    add_arrays(arr, arr + 4, out, 4);
    if (out[0] != 6 || out[1] != 8 || out[2] != 10 || out[3] != 12)
        return 1;

    /* Aliasing case: output overlaps input */
    int data[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    add_aliased(data, data + 1, data, 4);
    /* Sequential execution:
       i=0: data[0] = data[0]+data[1] = 1+2 = 3
       i=1: data[1] = data[1]+data[2] = 2+3 = 5
       i=2: data[2] = data[2]+data[3] = 3+4 = 7
       i=3: data[3] = data[3]+data[4] = 4+5 = 9 */
    if (data[0] != 3 || data[1] != 5 || data[2] != 7 || data[3] != 9)
        return 2;

    return 0;
}

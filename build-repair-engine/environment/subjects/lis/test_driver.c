#include <stdio.h>
#include <stdlib.h>

extern int lis_length(const int *arr, int n);
extern int array_max(const int *arr, int n);
extern int array_min(const int *arr, int n);
extern int is_sorted(const int *arr, int n);

typedef int (*test_func)(void);

/* empty */
int test_0(void) {
    return (lis_length(NULL, 0) == 0) ? 0 : 1;
}

/* single element */
int test_1(void) {
    int a[] = {7};
    return (lis_length(a, 1) == 1) ? 0 : 1;
}

/* strictly increasing */
int test_2(void) {
    int a[] = {1, 2, 3, 4, 5};
    return (lis_length(a, 5) == 5) ? 0 : 1;
}

/* strictly decreasing */
int test_3(void) {
    int a[] = {5, 4, 3, 2, 1};
    return (lis_length(a, 5) == 1) ? 0 : 1;
}

/* mixed */
int test_4(void) {
    int a[] = {3, 1, 2, 4};
    return (lis_length(a, 4) == 3) ? 0 : 1;
}

/* all equal => LIS is 1 (strictly increasing) */
int test_5(void) {
    int a[] = {2, 2, 2, 2};
    return (lis_length(a, 4) == 1) ? 0 : 1;
}

/* classic example */
int test_6(void) {
    int a[] = {10, 22, 9, 33, 21, 50, 41, 60};
    /* LIS: 10,22,33,50,60 => length 5 */
    return (lis_length(a, 8) == 5) ? 0 : 1;
}

/* helper tests: is_sorted */
int test_7(void) {
    int a[] = {1, 3, 5, 7};
    int b[] = {4, 2, 6};
    return (is_sorted(a, 4) == 1 && is_sorted(b, 3) == 0) ? 0 : 1;
}

int main(int argc, char *argv[]) {
    test_func tests[] = {test_0, test_1, test_2, test_3,
                         test_4, test_5, test_6, test_7};
    int n_tests = sizeof(tests) / sizeof(tests[0]);
    int start = 0, end = n_tests;
    if (argc > 1) {
        int t = atoi(argv[1]);
        if (t >= 0 && t < n_tests) { start = t; end = t + 1; }
    }
    int all_pass = 1;
    for (int i = start; i < end; i++) {
        int r = tests[i]();
        printf("%s: test_%d\n", r == 0 ? "PASS" : "FAIL", i);
        if (r != 0) all_pass = 0;
    }
    return all_pass ? 0 : 1;
}

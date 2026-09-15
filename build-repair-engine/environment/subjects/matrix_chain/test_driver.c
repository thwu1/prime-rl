#include <stdio.h>
#include <stdlib.h>

extern int matrix_chain_order(const int *dims, int n);
extern int can_multiply(int cols_a, int rows_b);
extern int mult_cost(int r1, int c1, int c2);
extern int total_elements(const int *dims, int n);

typedef int (*test_func)(void);

/* single matrix: 0 multiplications */
int test_0(void) {
    int dims[] = {10, 20};
    return (matrix_chain_order(dims, 1) == 0) ? 0 : 1;
}

/* two matrices: 10x20 * 20x30 = 6000 */
int test_1(void) {
    int dims[] = {10, 20, 30};
    return (matrix_chain_order(dims, 2) == 6000) ? 0 : 1;
}

/* classic: dims=[10,30,5,60] => 4500 */
int test_2(void) {
    int dims[] = {10, 30, 5, 60};
    return (matrix_chain_order(dims, 3) == 4500) ? 0 : 1;
}

/* dims=[1,2,3,4] => 18 */
int test_3(void) {
    int dims[] = {1, 2, 3, 4};
    return (matrix_chain_order(dims, 3) == 18) ? 0 : 1;
}

/* uniform dims: [5,5,5,5] - bug doesn't manifest */
int test_4(void) {
    int dims[] = {5, 5, 5, 5};
    return (matrix_chain_order(dims, 3) == 250) ? 0 : 1;
}

/* dims=[40,20,30,10,30] => 26000 */
int test_5(void) {
    int dims[] = {40, 20, 30, 10, 30};
    return (matrix_chain_order(dims, 4) == 26000) ? 0 : 1;
}

/* helper: can_multiply */
int test_6(void) {
    return (can_multiply(3, 3) == 1 && can_multiply(3, 4) == 0) ? 0 : 1;
}

/* helper: mult_cost */
int test_7(void) {
    return (mult_cost(2, 3, 4) == 24) ? 0 : 1;
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

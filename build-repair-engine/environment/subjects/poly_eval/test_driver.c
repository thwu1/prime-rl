#include <stdio.h>
#include <stdlib.h>

extern int poly_eval(const int *coeffs, int n, int x);
extern void poly_derivative(const int *coeffs, int n, int *deriv, int *dn);
extern int poly_add(const int *a, int na, const int *b, int nb, int *out);
extern int poly_degree(const int *coeffs, int n);

typedef int (*test_func)(void);

/* poly_eval: single coeff */
int test_0(void) {
    int c[] = {5};
    return (poly_eval(c, 1, 10) == 5) ? 0 : 1;
}

/* poly_eval: all zero non-leading coeffs */
int test_1(void) {
    int c[] = {0, 0, 1};
    return (poly_eval(c, 3, 2) == 4) ? 0 : 1;
}

/* poly_eval: 1 + 2x + 3x^2 at x=0 => 1 */
int test_2(void) {
    int c[] = {1, 2, 3};
    return (poly_eval(c, 3, 0) == 1) ? 0 : 1;
}

/* poly_eval: 1 + x at x=1 => 2 */
int test_3(void) {
    int c[] = {1, 1};
    return (poly_eval(c, 2, 1) == 2) ? 0 : 1;
}

/* poly_eval: 3 + 2x + x^2 at x=2 => 11 */
int test_4(void) {
    int c[] = {3, 2, 1};
    return (poly_eval(c, 3, 2) == 11) ? 0 : 1;
}

/* poly_derivative: d/dx (3 + 2x + x^2) = 2 + 2x */
int test_5(void) {
    int c[] = {3, 2, 1};
    int deriv[2];
    int dn;
    poly_derivative(c, 3, deriv, &dn);
    return (dn == 2 && deriv[0] == 2 && deriv[1] == 2) ? 0 : 1;
}

/* poly_add: [1,2] + [3,4,5] = [4,6,5] */
int test_6(void) {
    int a[] = {1, 2};
    int b[] = {3, 4, 5};
    int out[3];
    int n = poly_add(a, 2, b, 3, out);
    return (n == 3 && out[0] == 4 && out[1] == 6 && out[2] == 5) ? 0 : 1;
}

/* poly_eval: 2 + 3x at x=4 => 14 */
int test_7(void) {
    int c[] = {2, 3};
    return (poly_eval(c, 2, 4) == 14) ? 0 : 1;
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

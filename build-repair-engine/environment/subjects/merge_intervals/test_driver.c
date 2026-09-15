#include <stdio.h>
#include <stdlib.h>

typedef struct { int start; int end; } Interval;
extern int merge_intervals(Interval *in, int n, Interval *out);
extern int total_span(const Interval *intervals, int n);
extern int point_in_intervals(const Interval *intervals, int n, int pt);

typedef int (*test_func)(void);

int test_0(void) {
    Interval in[] = {{1,2}, {4,5}, {7,8}};
    Interval out[3];
    int n = merge_intervals(in, 3, out);
    return (n == 3 && out[0].start == 1 && out[0].end == 2 &&
            out[1].start == 4 && out[1].end == 5 &&
            out[2].start == 7 && out[2].end == 8) ? 0 : 1;
}

int test_1(void) {
    Interval in[] = {{1,4}, {2,6}};
    Interval out[2];
    int n = merge_intervals(in, 2, out);
    return (n == 1 && out[0].start == 1 && out[0].end == 6) ? 0 : 1;
}

int test_2(void) {
    Interval in[] = {{1,3}, {3,5}};
    Interval out[2];
    int n = merge_intervals(in, 2, out);
    return (n == 1 && out[0].start == 1 && out[0].end == 5) ? 0 : 1;
}

int test_3(void) {
    Interval in[] = {{1,4}, {2,6}, {8,10}, {15,18}};
    Interval out[4];
    int n = merge_intervals(in, 4, out);
    return (n == 3 && out[0].start == 1 && out[0].end == 6 &&
            out[1].start == 8 && out[1].end == 10 &&
            out[2].start == 15 && out[2].end == 18) ? 0 : 1;
}

int test_4(void) {
    Interval in[] = {{5,10}};
    Interval out[1];
    int n = merge_intervals(in, 1, out);
    return (n == 1 && out[0].start == 5 && out[0].end == 10) ? 0 : 1;
}

int test_5(void) {
    Interval out[1];
    int n = merge_intervals(NULL, 0, out);
    return (n == 0) ? 0 : 1;
}

int test_6(void) {
    Interval in[] = {{1,2}, {2,3}, {3,4}};
    Interval out[3];
    int n = merge_intervals(in, 3, out);
    return (n == 1 && out[0].start == 1 && out[0].end == 4) ? 0 : 1;
}

int test_7(void) {
    Interval in[] = {{1,10}, {3,5}};
    Interval out[2];
    int n = merge_intervals(in, 2, out);
    return (n == 1 && out[0].start == 1 && out[0].end == 10) ? 0 : 1;
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

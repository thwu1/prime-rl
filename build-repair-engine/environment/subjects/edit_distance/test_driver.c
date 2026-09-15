#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern int edit_distance(const char *s1, const char *s2);
extern int char_diff_count(const char *s1, const char *s2);
extern int common_prefix_len(const char *s1, const char *s2);

typedef int (*test_func)(void);

int test_0(void) {
    return (edit_distance("", "") == 0) ? 0 : 1;
}

int test_1(void) {
    return (edit_distance("abc", "abc") == 0) ? 0 : 1;
}

int test_2(void) {
    return (edit_distance("", "hello") == 5) ? 0 : 1;
}

int test_3(void) {
    return (edit_distance("world", "") == 5) ? 0 : 1;
}

int test_4(void) {
    return (edit_distance("abc", "def") == 3) ? 0 : 1;
}

int test_5(void) {
    return (edit_distance("kitten", "sitting") == 3) ? 0 : 1;
}

int test_6(void) {
    return (edit_distance("horse", "ros") == 3) ? 0 : 1;
}

int test_7(void) {
    return (edit_distance("intention", "execution") == 5) ? 0 : 1;
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

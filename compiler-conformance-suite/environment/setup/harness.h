/*
 * harness.h — Self-checking test harness for C compiler conformance tests
 *
 * Inspired by the SuperTest validation framework methodology.
 * Each test uses TEST_INIT, TEST_VERIFY, and TEST_RESULT macros
 * to create self-checking programs that report PASS or FAIL.
 */
#ifndef HARNESS_H
#define HARNESS_H

#include <stdio.h>
#include <stdlib.h>

static int _test_failures = 0;
static int _test_count = 0;
static const char *_test_name = "";

#define TEST_INIT(name) do { \
    _test_name = (name); \
    _test_failures = 0; \
    _test_count = 0; \
} while (0)

#define TEST_VERIFY(expr) do { \
    _test_count++; \
    if (!(expr)) { \
        _test_failures++; \
        fprintf(stderr, "FAIL: %s:%d: %s\n", __FILE__, __LINE__, #expr); \
    } \
} while (0)

#define TEST_RESULT() do { \
    if (_test_failures == 0) \
        printf("PASS: %s (%d checks)\n", _test_name, _test_count); \
    else \
        printf("FAIL: %s (%d/%d checks failed)\n", \
               _test_name, _test_failures, _test_count); \
    return _test_failures ? 1 : 0; \
} while (0)

#endif /* HARNESS_H */

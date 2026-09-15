
#include <stdio.h>
#include <string.h>
#include "hsm.h"
#include "test_sm3.h"

static int test_num = 0;
static int pass_count = 0;
static int fail_count = 0;

static void check_trace(Hsm *sm, const char *expected, const char *desc) {
    test_num++;
    const char *actual = hsm_trace(sm);
    if (strcmp(actual, expected) == 0) {
        printf("PASS %d: %s\n", test_num, desc);
        pass_count++;
    } else {
        printf("FAIL %d: %s\n  expected: \"%s\"\n  actual:   \"%s\"\n",
               test_num, desc, expected, actual);
        fail_count++;
    }
    hsm_trace_clear(sm);
}

int main(void) {
    GuardSm sm;
    sm.guard_val = 0;
    hsm_ctor(&sm.super, sm3_initial);

    /* Test 1: Init drills G1 -> G11 */
    hsm_init(&sm.super);
    check_trace(&sm.super,
        "EN-G1;EN-G11;",
        "init drills to G11 via G1->G11");

    /* Test 2: SIG3_P guard passes (guard_val=1), G11 -> G12 */
    sm.guard_val = 1;
    hsm_dispatch(&sm.super, SIG3_P);
    check_trace(&sm.super,
        "EX-G11;EN-G12;",
        "G11->G12 guard passes (guard_val>0)");

    /* Test 3: SIG3_S, G12 -> G11 (unconditional sibling) */
    hsm_dispatch(&sm.super, SIG3_S);
    check_trace(&sm.super,
        "EX-G12;EN-G11;",
        "G12->G11 unconditional sibling");

    /* Test 4: SIG3_P guard fails (guard_val=0), propagates to G1 -> G21 */
    sm.guard_val = 0;
    hsm_dispatch(&sm.super, SIG3_P);
    check_trace(&sm.super,
        "EX-G11;EX-G1;EN-G2;EN-G21;",
        "G11 guard fails, G1 fallback -> G21");

    /* Test 5: SIG3_Q guard passes (guard_val=1), G21 -> G11 */
    sm.guard_val = 1;
    hsm_dispatch(&sm.super, SIG3_Q);
    check_trace(&sm.super,
        "EX-G21;EX-G2;EN-G1;EN-G11;",
        "G21->G11 guard passes (guard_val>0)");

    /* Test 6: SIG3_R, G11 -> G21 (unconditional cross-hierarchy) */
    hsm_dispatch(&sm.super, SIG3_R);
    check_trace(&sm.super,
        "EX-G11;EX-G1;EN-G2;EN-G21;",
        "G11->G21 unconditional cross-hierarchy");

    /* Test 7: SIG3_Q guard fails (guard_val=0), propagates to G2 -> G12 */
    sm.guard_val = 0;
    hsm_dispatch(&sm.super, SIG3_Q);
    check_trace(&sm.super,
        "EX-G21;EX-G2;EN-G1;EN-G12;",
        "G21 guard fails, G2 fallback -> G12");

    /* Test 8: SIG3_T from G12, delegated to G1 -> G2 (composite, inits G21) */
    hsm_dispatch(&sm.super, SIG3_T);
    check_trace(&sm.super,
        "EX-G12;EX-G1;EN-G2;EN-G21;",
        "G12 delegates SIG3_T to G1 -> G2 composite (inits G21)");

    /* Summary */
    printf("\n%d/%d guard tests passed\n", pass_count, test_num);
    return (fail_count == 0) ? 0 : 1;
}

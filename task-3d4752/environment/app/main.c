
#include <stdio.h>
#include <string.h>
#include "hsm.h"
#include "test_sm.h"

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
    Hsm sm;

    /* Construct with sm_initial as the initial pseudo-state */
    hsm_ctor(&sm, sm_initial);

    /* Test 1: Initialization drills through S1 -> S11 -> S111 */
    hsm_init(&sm);
    check_trace(&sm,
        "ENTRY-S1;ENTRY-S11;ENTRY-S111;",
        "init drills to S111 via S1->S11->S111");

    /* Test 2: SIG_A in S111 -> S112 (sibling transition, same parent S11) */
    hsm_dispatch(&sm, SIG_A);
    check_trace(&sm,
        "EXIT-S111;ENTRY-S112;",
        "S111->S112 sibling transition");

    /* Test 3: SIG_B in S112 -> S211 (cross-hierarchy, LCA=top) */
    hsm_dispatch(&sm, SIG_B);
    check_trace(&sm,
        "EXIT-S112;EXIT-S11;EXIT-S1;ENTRY-S2;ENTRY-S21;ENTRY-S211;",
        "S112->S211 cross-hierarchy");

    /* Test 4: SIG_C in S211 -> S11 (cross-hierarchy, target has init chain) */
    hsm_dispatch(&sm, SIG_C);
    check_trace(&sm,
        "EXIT-S211;EXIT-S21;EXIT-S2;ENTRY-S1;ENTRY-S11;ENTRY-S111;",
        "S211->S11 with init drill to S111");

    /* Test 5: SIG_G in S111 -> S111 (self-transition: exit then re-enter) */
    hsm_dispatch(&sm, SIG_G);
    check_trace(&sm,
        "EXIT-S111;ENTRY-S111;",
        "S111->S111 self-transition");

    /* Test 6: SIG_E in S111, handled by ancestor S1, -> S3 */
    hsm_dispatch(&sm, SIG_E);
    check_trace(&sm,
        "EXIT-S111;EXIT-S11;EXIT-S1;ENTRY-S3;",
        "SIG_E bubbles S111->S11->S1, S1 transitions to S3");

    /* Test 7: SIG_F in S3 -> S111 (shallow to deep) */
    hsm_dispatch(&sm, SIG_F);
    check_trace(&sm,
        "EXIT-S3;ENTRY-S1;ENTRY-S11;ENTRY-S111;",
        "S3->S111 shallow to deep");

    /* Test 8: SIG_D in S111 -> S1 (to ancestor, re-init drills back) */
    hsm_dispatch(&sm, SIG_D);
    check_trace(&sm,
        "EXIT-S111;EXIT-S11;ENTRY-S11;ENTRY-S111;",
        "S111->S1 to ancestor, re-inits to S111");

    /* Test 9: SIG_H in S111, handled by S11, -> S21 (mid-level cross) */
    hsm_dispatch(&sm, SIG_H);
    check_trace(&sm,
        "EXIT-S111;EXIT-S11;EXIT-S1;ENTRY-S2;ENTRY-S21;ENTRY-S211;",
        "SIG_H bubbles S111->S11, S11 transitions to S21->S211");

    /* Test 10: SIG_A in S211 - not handled by any state, no transition */
    hsm_dispatch(&sm, SIG_A);
    check_trace(&sm,
        "",
        "SIG_A unhandled in S211 hierarchy, no transition");

    /* Summary */
    printf("\n%d/%d tests passed\n", pass_count, test_num);
    return (fail_count == 0) ? 0 : 1;
}

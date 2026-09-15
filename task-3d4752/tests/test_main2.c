
#include <stdio.h>
#include <string.h>
#include "hsm.h"
#include "test_sm2.h"

static int tests = 0, passed = 0;

static void check(Hsm *sm, const char *exp, const char *desc) {
    tests++;
    const char *got = hsm_trace(sm);
    if (strcmp(got, exp) == 0) {
        passed++;
        printf("PASS %d: %s\n", tests, desc);
    } else {
        printf("FAIL %d: %s\n  exp: \"%s\"\n  got: \"%s\"\n",
               tests, desc, exp, got);
    }
    hsm_trace_clear(sm);
}

int main(void) {
    Hsm sm;
    hsm_ctor(&sm, sm2_initial);

    /* Test 1: init drills A -> A1 */
    hsm_init(&sm);
    check(&sm, "EN-A;EN-A1;", "init drills A->A1");

    /* Test 2: SIG2_X: A1 -> A2 (sibling) */
    hsm_dispatch(&sm, SIG2_X);
    check(&sm, "EX-A1;EN-A2;", "A1->A2 sibling");

    /* Test 3: SIG2_Y: A2 -> B1 (cross-hierarchy) */
    hsm_dispatch(&sm, SIG2_Y);
    check(&sm, "EX-A2;EX-A;EN-B;EN-B1;", "A2->B1 cross-hierarchy");

    /* Test 4: SIG2_Z: B1 -> A (to composite with init) */
    hsm_dispatch(&sm, SIG2_Z);
    check(&sm, "EX-B1;EX-B;EN-A;EN-A1;", "B1->A with init drill");

    /* Test 5: SIG2_W: A1 -> A1 (self-transition) */
    hsm_dispatch(&sm, SIG2_W);
    check(&sm, "EX-A1;EN-A1;", "A1->A1 self-transition");

    /* Test 6: SIG2_V: A1 (handled by ancestor A) -> B1 */
    hsm_dispatch(&sm, SIG2_V);
    check(&sm, "EX-A1;EX-A;EN-B;EN-B1;", "SIG2_V bubbles A1->A, A->B1");

    /* Summary */
    printf("\n%d/%d passed\n", passed, tests);
    return (passed == tests) ? 0 : 1;
}

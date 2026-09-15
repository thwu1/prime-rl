
#include <stdio.h>
#include <string.h>
#include "hsm.h"
#include "test_sm.h"

static int pass_count = 0;
static int fail_count = 0;

static void assert_in(Hsm *sm, HsmStateHandler s, const char *name, int expected) {
    int result = hsm_is_in(sm, s) ? 1 : 0;
    if (result == expected) {
        printf("PASS is_in(%s)==%d\n", name, expected);
        pass_count++;
    } else {
        printf("FAIL is_in(%s): got %d, expected %d\n", name, result, expected);
        fail_count++;
    }
}

int main(void) {
    Hsm sm;
    hsm_ctor(&sm, sm_initial);
    hsm_init(&sm);
    /* After init: active state is S111 (inside S11, S1, top) */

    /* Positive: should be in S111, S11, S1, top */
    assert_in(&sm, sm_S111, "S111", 1);
    assert_in(&sm, sm_S11,  "S11",  1);
    assert_in(&sm, sm_S1,   "S1",   1);
    assert_in(&sm, hsm_top, "top",  1);

    /* Negative: should NOT be in sibling/cousin states */
    assert_in(&sm, sm_S112, "S112", 0);
    assert_in(&sm, sm_S12,  "S12",  0);
    assert_in(&sm, sm_S2,   "S2",   0);
    assert_in(&sm, sm_S21,  "S21",  0);
    assert_in(&sm, sm_S211, "S211", 0);
    assert_in(&sm, sm_S3,   "S3",   0);

    /* Verify dispatch still works correctly after is_in queries */
    hsm_trace_clear(&sm);
    hsm_dispatch(&sm, SIG_A);  /* S111 -> S112 */
    if (strcmp(hsm_trace(&sm), "EXIT-S111;ENTRY-S112;") == 0) {
        printf("PASS dispatch_after_is_in\n");
        pass_count++;
    } else {
        printf("FAIL dispatch_after_is_in: got '%s'\n", hsm_trace(&sm));
        fail_count++;
    }

    /* After transition to S112: verify is_in reflects new state */
    assert_in(&sm, sm_S112, "S112_new", 1);
    assert_in(&sm, sm_S11,  "S11_still", 1);
    assert_in(&sm, sm_S111, "S111_old", 0);

    printf("\n%d/%d is_in tests passed\n", pass_count, pass_count + fail_count);
    return (fail_count == 0) ? 0 : 1;
}

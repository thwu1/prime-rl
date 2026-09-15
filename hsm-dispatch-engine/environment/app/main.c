/*
 * Test driver — dispatches a sequence of signals and prints execution traces.
 *
 */

#include <stdio.h>
#include "hsm.h"
#include "qhsmtst.h"
#include "trace.h"

int main(void) {
    qhsmtst_ctor();

    trace_clear();
    hsm_init(&the_hsm.super);
    printf("INIT: %s\n", trace_get());

    static const struct { int sig; const char *name; } events[] = {
        { G_SIG, "G" },  /*  1 — cross-branch tran (s21→s1) */
        { I_SIG, "I" },  /*  2 — internal tran (handled by s1) */
        { A_SIG, "A" },  /*  3 — self-transition on s1 */
        { D_SIG, "D" },  /*  4 — guard: foo=0, s11 UNHANDLED → s1 handles */
        { D_SIG, "D" },  /*  5 — guard: foo=1, s11 handles */
        { C_SIG, "C" },  /*  6 — sibling tran (s1→s2) */
        { F_SIG, "F" },  /*  7 — cross-branch tran (s2→s11) */
        { F_SIG, "F" },  /*  8 — cross-branch tran (s1→s211) */
        { E_SIG, "E" },  /*  9 — deep tran from grandparent (s→s11) */
        { H_SIG, "H" },  /* 10 — deep tran to grandparent (s11→s) */
        { B_SIG, "B" },  /* 11 — parent-to-child (s1→s11) */
        { G_SIG, "G" },  /* 12 — cross-branch (s11→s211) */
        { I_SIG, "I" },  /* 13 — guard: foo=0, s2 handles (internal) */
        { I_SIG, "I" },  /* 14 — guard: foo=1, s2 UNHANDLED → s handles */
        { H_SIG, "H" },  /* 15 — deep tran (s211→s) */
        { C_SIG, "C" },  /* 16 — sibling tran (s1→s2) */
        { B_SIG, "B" },  /* 17 — parent-to-child (s21→s211) */
        { D_SIG, "D" },  /* 18 — child-to-parent (s211→s21) */
    };
    int n = (int)(sizeof(events) / sizeof(events[0]));

    for (int i = 0; i < n; i++) {
        trace_clear();
        hsm_dispatch(&the_hsm.super, events[i].sig);
        printf("Signal %s: %s\n", events[i].name, trace_get());
    }

    return 0;
}

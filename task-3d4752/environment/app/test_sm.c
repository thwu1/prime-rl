
#include "test_sm.h"

/*
 * Test State Machine Topology:
 *
 *                          top
 *                      /    |    \
 *                    S1     S2    S3
 *                  /    \    |
 *                S11    S12  S21
 *               /   \        |
 *             S111  S112    S211
 *
 * Initial transitions:
 *   top -> S1 (via initial pseudo-state)
 *   S1  -> S11
 *   S11 -> S111
 *   S21 -> S211
 *
 * Signal routing:
 *   SIG_A: S111 -> S112  (sibling transition)
 *   SIG_B: S112 -> S211  (cross-hierarchy, deep)
 *   SIG_C: S211 -> S11   (cross-hierarchy, target has init chain)
 *   SIG_D: S111 -> S1    (to ancestor, triggers re-initialization)
 *   SIG_E: S1   -> S3    (handled at ancestor level)
 *   SIG_F: S3   -> S111  (shallow to deep)
 *   SIG_G: S111 -> S111  (self-transition)
 *   SIG_H: S11  -> S21   (mid-level cross-hierarchy)
 */

HsmState sm_initial(Hsm *me, int sig) {
    (void)sig;
    return HSM_TRAN_TO(me, sm_S1);
}

HsmState sm_S1(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S1;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S1;");
            return HSM_HANDLED;
        case HSM_SIG_INIT:
            return HSM_TRAN_TO(me, sm_S11);
        case SIG_E:
            return HSM_TRAN_TO(me, sm_S3);
        default:
            return HSM_SUPER_OF(me, hsm_top);
    }
}

HsmState sm_S11(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S11;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S11;");
            return HSM_HANDLED;
        case HSM_SIG_INIT:
            return HSM_TRAN_TO(me, sm_S111);
        case SIG_H:
            return HSM_TRAN_TO(me, sm_S21);
        default:
            return HSM_SUPER_OF(me, sm_S1);
    }
}

HsmState sm_S111(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S111;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S111;");
            return HSM_HANDLED;
        case SIG_A:
            return HSM_TRAN_TO(me, sm_S112);
        case SIG_D:
            return HSM_TRAN_TO(me, sm_S1);
        case SIG_G:
            return HSM_TRAN_TO(me, sm_S111);
        default:
            return HSM_SUPER_OF(me, sm_S11);
    }
}

HsmState sm_S112(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S112;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S112;");
            return HSM_HANDLED;
        case SIG_B:
            return HSM_TRAN_TO(me, sm_S211);
        default:
            return HSM_SUPER_OF(me, sm_S11);
    }
}

HsmState sm_S12(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S12;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S12;");
            return HSM_HANDLED;
        default:
            return HSM_SUPER_OF(me, sm_S1);
    }
}

HsmState sm_S2(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S2;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S2;");
            return HSM_HANDLED;
        default:
            return HSM_SUPER_OF(me, hsm_top);
    }
}

HsmState sm_S21(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S21;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S21;");
            return HSM_HANDLED;
        case HSM_SIG_INIT:
            return HSM_TRAN_TO(me, sm_S211);
        default:
            return HSM_SUPER_OF(me, sm_S2);
    }
}

HsmState sm_S211(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S211;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S211;");
            return HSM_HANDLED;
        case SIG_C:
            return HSM_TRAN_TO(me, sm_S11);
        default:
            return HSM_SUPER_OF(me, sm_S21);
    }
}

HsmState sm_S3(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "ENTRY-S3;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EXIT-S3;");
            return HSM_HANDLED;
        case SIG_F:
            return HSM_TRAN_TO(me, sm_S111);
        default:
            return HSM_SUPER_OF(me, hsm_top);
    }
}


#include "test_sm2.h"

/*
 * Secondary Test State Machine:
 *
 *          top
 *         /   \
 *        A     B
 *       / \     \
 *      A1  A2    B1
 *
 * Init: top -> A, A -> A1
 *
 * SIG2_X: A1 -> A2  (sibling)
 * SIG2_Y: A2 -> B1  (cross-hierarchy)
 * SIG2_Z: B1 -> A   (to composite with init chain)
 * SIG2_W: A1 -> A1  (self-transition)
 * SIG2_V: A  -> B1  (handled at ancestor, cross-hierarchy)
 */

HsmState sm2_initial(Hsm *me, int sig) {
    (void)sig;
    return HSM_TRAN_TO(me, sm2_A);
}

HsmState sm2_A(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-A;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-A;");
            return HSM_HANDLED;
        case HSM_SIG_INIT:
            return HSM_TRAN_TO(me, sm2_A1);
        case SIG2_V:
            return HSM_TRAN_TO(me, sm2_B1);
        default:
            return HSM_SUPER_OF(me, hsm_top);
    }
}

HsmState sm2_A1(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-A1;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-A1;");
            return HSM_HANDLED;
        case SIG2_X:
            return HSM_TRAN_TO(me, sm2_A2);
        case SIG2_W:
            return HSM_TRAN_TO(me, sm2_A1);
        default:
            return HSM_SUPER_OF(me, sm2_A);
    }
}

HsmState sm2_A2(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-A2;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-A2;");
            return HSM_HANDLED;
        case SIG2_Y:
            return HSM_TRAN_TO(me, sm2_B1);
        default:
            return HSM_SUPER_OF(me, sm2_A);
    }
}

HsmState sm2_B(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-B;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-B;");
            return HSM_HANDLED;
        default:
            return HSM_SUPER_OF(me, hsm_top);
    }
}

HsmState sm2_B1(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-B1;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-B1;");
            return HSM_HANDLED;
        case SIG2_Z:
            return HSM_TRAN_TO(me, sm2_A);
        default:
            return HSM_SUPER_OF(me, sm2_B);
    }
}

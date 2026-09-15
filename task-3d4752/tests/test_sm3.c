
#include "test_sm3.h"

/*
 * Guard State Machine Implementation:
 *
 *              top
 *             /   \
 *           G1     G2
 *          / \      \
 *        G11  G12   G21
 *
 * Guard condition routing (guard_val from GuardSm):
 *   SIG3_P at G11: guard_val > 0 -> TRAN(G12), else UNHANDLED -> G1 handles
 *   SIG3_P at G1:  (fallback) TRAN(G21)
 *   SIG3_Q at G21: guard_val > 0 -> TRAN(G11), else UNHANDLED -> G2 handles
 *   SIG3_Q at G2:  (fallback) TRAN(G12)
 *   SIG3_R at G11: unconditional TRAN(G21)
 *   SIG3_S at G12: unconditional TRAN(G11)
 *   SIG3_T at G1:  unconditional TRAN(G2)  (composite target, inits to G21)
 *
 * Initial transitions:
 *   top -> G1 -> G11
 *   G2  -> G21
 */

HsmState sm3_initial(Hsm *me, int sig) {
    (void)sig;
    return HSM_TRAN_TO(me, sm3_G1);
}

HsmState sm3_G1(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-G1;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-G1;");
            return HSM_HANDLED;
        case HSM_SIG_INIT:
            return HSM_TRAN_TO(me, sm3_G11);
        case SIG3_P:
            return HSM_TRAN_TO(me, sm3_G21);
        case SIG3_T:
            return HSM_TRAN_TO(me, sm3_G2);
        default:
            return HSM_SUPER_OF(me, hsm_top);
    }
}

HsmState sm3_G11(Hsm *me, int sig) {
    GuardSm *g = (GuardSm *)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-G11;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-G11;");
            return HSM_HANDLED;
        case SIG3_P:
            if (g->guard_val > 0) {
                return HSM_TRAN_TO(me, sm3_G12);
            }
            return HSM_UNHANDLED;
        case SIG3_R:
            return HSM_TRAN_TO(me, sm3_G21);
        default:
            return HSM_SUPER_OF(me, sm3_G1);
    }
}

HsmState sm3_G12(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-G12;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-G12;");
            return HSM_HANDLED;
        case SIG3_S:
            return HSM_TRAN_TO(me, sm3_G11);
        default:
            return HSM_SUPER_OF(me, sm3_G1);
    }
}

HsmState sm3_G2(Hsm *me, int sig) {
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-G2;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-G2;");
            return HSM_HANDLED;
        case HSM_SIG_INIT:
            return HSM_TRAN_TO(me, sm3_G21);
        case SIG3_Q:
            return HSM_TRAN_TO(me, sm3_G12);
        default:
            return HSM_SUPER_OF(me, hsm_top);
    }
}

HsmState sm3_G21(Hsm *me, int sig) {
    GuardSm *g = (GuardSm *)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            hsm_trace_append(me, "EN-G21;");
            return HSM_HANDLED;
        case HSM_SIG_EXIT:
            hsm_trace_append(me, "EX-G21;");
            return HSM_HANDLED;
        case SIG3_Q:
            if (g->guard_val > 0) {
                return HSM_TRAN_TO(me, sm3_G11);
            }
            return HSM_UNHANDLED;
        default:
            return HSM_SUPER_OF(me, sm3_G2);
    }
}

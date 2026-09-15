
#ifndef TEST_SM3_H
#define TEST_SM3_H

#include "hsm.h"

/*
 * Guard State Machine Topology:
 *
 *              top
 *             /   \
 *           G1     G2
 *          / \      \
 *        G11  G12   G21
 *
 * GuardSm extends Hsm with guard_val field used for guard conditions.
 * Handlers returning HSM_UNHANDLED cause the event to propagate upward.
 */

typedef struct {
    Hsm super;      /* must be first member (struct polymorphism) */
    int guard_val;  /* guard condition input */
} GuardSm;

/* Signals */
#define SIG3_P  (HSM_SIG_USER + 0)
#define SIG3_Q  (HSM_SIG_USER + 1)
#define SIG3_R  (HSM_SIG_USER + 2)
#define SIG3_S  (HSM_SIG_USER + 3)
#define SIG3_T  (HSM_SIG_USER + 4)

/* State handler declarations */
HsmState sm3_initial(Hsm *me, int sig);
HsmState sm3_G1(Hsm *me, int sig);
HsmState sm3_G11(Hsm *me, int sig);
HsmState sm3_G12(Hsm *me, int sig);
HsmState sm3_G2(Hsm *me, int sig);
HsmState sm3_G21(Hsm *me, int sig);

#endif /* TEST_SM3_H */

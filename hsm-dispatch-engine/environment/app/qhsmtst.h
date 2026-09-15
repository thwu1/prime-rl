/*
 * QHsmTst — canonical test state machine for hierarchical state machines.
 *
 */

#ifndef QHSMTST_H
#define QHSMTST_H

#include "hsm.h"

/* User-defined signals for the test state machine */
enum QHsmTstSignals {
    A_SIG = HSM_SIG_USER,
    B_SIG,
    C_SIG,
    D_SIG,
    E_SIG,
    F_SIG,
    G_SIG,
    H_SIG,
    I_SIG,
    MAX_SIG
};

/* QHsmTst state machine structure — extends Hsm */
typedef struct {
    Hsm super;       /* HSM base (MUST be first member) */
    uint8_t foo;     /* test variable used in guard conditions */
} QHsmTst;

/* Global instance */
extern QHsmTst the_hsm;

/* Constructor */
void qhsmtst_ctor(void);

#endif /* QHSMTST_H */

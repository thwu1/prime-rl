/*
 * test_sm.h - Test State Machine Definition
 *
 * Defines a hierarchical state machine with the following topology:
 *
 *              top
 *               |
 *               r        (init -> r1)
 *             /   \
 *           r1     r2    (init -> r211)
 *          / \      \
 *        r11  r12   r21  (init -> r211)
 *                    |
 *                  r211
 *
 * The initial pseudostate transitions to r2.
 */

#ifndef TEST_SM_H
#define TEST_SM_H

#include "hsm.h"

/* User-defined signals */
enum {
    P_SIG = HSM_USER_SIG,
    Q_SIG,
    R_SIG,
    S_SIG,
    T_SIG,
    U_SIG,
    V_SIG,
    W_SIG,
    X_SIG,
    MAX_SIG
};

/* Test state machine with a guard variable */
typedef struct {
    Hsm super;       /* Must be the first member (base class) */
    uint8_t foo;     /* Guard condition variable */
} TestSM;

/* Constructor */
void TestSM_ctor(TestSM *me);

/* Query current state name as a string */
const char *TestSM_state_name(TestSM *me);

/* Query guard variable */
uint8_t TestSM_get_foo(TestSM *me);

/* Global instance */
extern TestSM test_sm;

#endif /* TEST_SM_H */

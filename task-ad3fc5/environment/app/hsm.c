/*
 * hsm.c - Hierarchical State Machine Engine Implementation (SKELETON)
 *
 * You must implement hsm_init() and hsm_dispatch().
 * Study the header (hsm.h), handler protocol (spec.md), and the test
 * state machine (test_sm.c) to understand expected behavior.
 * Reference traces are in /app/traces/.
 *
 */
#include "hsm.h"
#include <assert.h>

/* Constructor: stores the initial pseudostate handler. */
void hsm_ctor(Hsm *me, HsmStateHandler initial) {
    me->state = (HsmStateHandler)hsm_top;
    me->temp  = initial;
}

/* Top state: the root of every state hierarchy.
 * Ignores all events (returns HSM_RET_IGNORED). */
HsmRet hsm_top(Hsm *me, const HsmEvent *e) {
    (void)me;
    (void)e;
    return HSM_RET_IGNORED;
}

/* Initialize the state machine.
 *
 * Precondition: me->state == hsm_top, me->temp == initial pseudostate handler
 * Postcondition: me->state == deepest leaf reachable via initial transitions
 */
void hsm_init(Hsm *me, const HsmEvent *e) {
    /* TODO: implement */
    (void)me;
    (void)e;
}

/* Dispatch an event to the state machine.
 *
 * Precondition: HSM is initialized (me->state is a valid leaf state)
 * Postcondition: me->state updated if a transition was taken
 */
void hsm_dispatch(Hsm *me, const HsmEvent *e) {
    /* TODO: implement */
    (void)me;
    (void)e;
}

/*
 * Hierarchical State Machine (HSM) Engine — Implementation
 *
 * Implement the functions below to provide a working UML Statechart engine.
 * Refer to hsm.h for the API contract and qhsmtst.c for usage patterns.
 *
 */

#include "hsm.h"

/*--------------------------------------------------------------------------*/
/* Top state — root of every hierarchy. Ignores all signals.                */
HsmState hsm_top(void *me, int sig) {
    (void)me;
    (void)sig;
    return HSM_RET_IGNORED;
}

/*--------------------------------------------------------------------------*/
/* Constructor: prepare an HSM instance for use.                            */
void hsm_ctor(Hsm *me, HsmStateHandler initial) {
    /* YOUR IMPLEMENTATION HERE */
    (void)me;
    (void)initial;
}

/*--------------------------------------------------------------------------*/
/* Execute the top-most initial transition and settle into the starting     */
/* state. Called once after hsm_ctor().                                     */
void hsm_init(Hsm *me) {
    /* YOUR IMPLEMENTATION HERE */
    (void)me;
}

/*--------------------------------------------------------------------------*/
/* Dispatch a signal through the state hierarchy according to UML           */
/* Statechart semantics, executing any resulting state transition.          */
void hsm_dispatch(Hsm *me, int sig) {
    /* YOUR IMPLEMENTATION HERE */
    (void)me;
    (void)sig;
}

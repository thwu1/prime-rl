/*
 * Hierarchical State Machine (HSM) Engine - Header
 *
 * Implements UML Statechart semantics for hierarchical state machines.
 *
 */

#ifndef HSM_H
#define HSM_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/*--------------------------------------------------------------------------*/
/* Return codes from state handlers                                         */
typedef uint_fast8_t HsmState;

#define HSM_RET_HANDLED   ((HsmState)0U)  /* event handled, no transition   */
#define HSM_RET_IGNORED   ((HsmState)1U)  /* event ignored (top state only) */
#define HSM_RET_SUPER     ((HsmState)2U)  /* event passed to superstate     */
#define HSM_RET_TRAN      ((HsmState)3U)  /* state transition taken         */
#define HSM_RET_UNHANDLED ((HsmState)4U)  /* guard failed, propagate up     */

/*--------------------------------------------------------------------------*/
/* Reserved signals                                                         */
#define HSM_SIG_EMPTY  0  /* query superstate (internal use only)            */
#define HSM_SIG_ENTRY  1  /* state entry action                             */
#define HSM_SIG_EXIT   2  /* state exit action                              */
#define HSM_SIG_INIT   3  /* initial transition within a composite state    */
#define HSM_SIG_USER   4  /* first user-defined signal                      */

/*--------------------------------------------------------------------------*/
/* Maximum state nesting depth (including the top state)                     */
#define HSM_MAX_NEST_DEPTH 6

/*--------------------------------------------------------------------------*/
/* State handler function pointer type.                                     */
/* Every state is represented by a function with this signature.            */
typedef HsmState (*HsmStateHandler)(void *me, int sig);

/*--------------------------------------------------------------------------*/
/* HSM base structure. Must be the FIRST member of any derived struct so    */
/* that casts between the derived type and Hsm* are valid.                  */
typedef struct {
    HsmStateHandler state;  /* current active state handler                 */
    HsmStateHandler temp;   /* scratch: superstate result or tran. target   */
} Hsm;

/*--------------------------------------------------------------------------*/
/* Macros for use INSIDE state handler functions.                           */
/* The handler's first parameter must be (void *me).                        */

/* Take a transition to target state. */
#define HSM_TRAN(target_) \
    (((Hsm *)(me))->temp = (HsmStateHandler)(target_), HSM_RET_TRAN)

/* Designate the superstate (parent) of this state. */
#define HSM_SUPER(super_) \
    (((Hsm *)(me))->temp = (HsmStateHandler)(super_), HSM_RET_SUPER)

/* Event handled internally (no state transition). */
#define HSM_HANDLED()   (HSM_RET_HANDLED)

/* Event not handled due to a guard condition failure; propagate upward. */
#define HSM_UNHANDLED() (HSM_RET_UNHANDLED)

/*--------------------------------------------------------------------------*/
/* Top state handler — the ultimate root of every state hierarchy.          */
/* All top-level user states must return HSM_SUPER(&hsm_top) as default.    */
HsmState hsm_top(void *me, int sig);

/*--------------------------------------------------------------------------*/
/* Public API                                                               */

/* Constructor. Sets current state to hsm_top, stores initial handler. */
void hsm_ctor(Hsm *me, HsmStateHandler initial);

/* Execute the top-most initial transition. Call once after hsm_ctor. */
void hsm_init(Hsm *me);

/* Dispatch a signal to the state machine. */
void hsm_dispatch(Hsm *me, int sig);

#endif /* HSM_H */

/*
 * hsm.h - Hierarchical State Machine (HSM) Engine API
 *
 * Defines data structures and function signatures for a hierarchical
 * state machine engine supporting entry/exit actions, nested initial
 * transitions, and guard conditions.
 */

#ifndef HSM_H
#define HSM_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Maximum depth of state nesting (including the top level). */
#define HSM_MAX_NEST_DEPTH 8

/* Reserved signals used internally by the HSM engine.
 * User-defined signals must start from HSM_USER_SIG. */
enum {
    HSM_EMPTY_SIG = 0,   /* Query superstate (internal use only)       */
    HSM_ENTRY_SIG = 1,   /* State entry action                         */
    HSM_EXIT_SIG  = 2,   /* State exit action                          */
    HSM_INIT_SIG  = 3,   /* Nested initial transition                  */
    HSM_USER_SIG  = 4    /* First user-definable signal                 */
};

/* Return values from state handler functions. */
typedef enum {
    HSM_RET_SUPER     = 0,  /* Designates the superstate of this state */
    HSM_RET_UNHANDLED = 1,  /* Event not handled (guard failed)        */
    HSM_RET_HANDLED   = 2,  /* Event handled, no state transition      */
    HSM_RET_TRAN      = 3,  /* State transition taken                  */
    HSM_RET_IGNORED   = 5   /* Event ignored (top state only)          */
} HsmRet;

/* Forward declarations */
typedef struct Hsm Hsm;
typedef struct HsmEvent HsmEvent;

/* Event structure: carries only the signal identifier. */
struct HsmEvent {
    uint16_t sig;
};

/* State handler function pointer type.
 * Every state is represented by a function with this signature. */
typedef HsmRet (*HsmStateHandler)(Hsm *me, const HsmEvent *e);

/* HSM instance structure.
 * Subclass this (as the first member) to add application-specific data. */
struct Hsm {
    HsmStateHandler state;  /* Current active state handler             */
    HsmStateHandler temp;   /* Temporary: used for superstate/target    */
};

/* ===== API Functions (to be implemented in hsm.c) ===================== */

/* Constructor: sets the initial pseudostate handler.
 * Must be called before hsm_init(). */
void hsm_ctor(Hsm *me, HsmStateHandler initial);

/* Initialize the HSM: executes the top-most initial transition and
 * drills down into the state hierarchy via nested initial transitions.
 * Must be called exactly once after hsm_ctor(). */
void hsm_init(Hsm *me, const HsmEvent *e);

/* Dispatch an event to the HSM: processes the event according to
 * hierarchical state machine semantics.
 * Must be called only after hsm_init(). */
void hsm_dispatch(Hsm *me, const HsmEvent *e);

/* The universal top state: root of all state hierarchies.
 * Returns HSM_RET_IGNORED for all events. */
HsmRet hsm_top(Hsm *me, const HsmEvent *e);

/* ===== Macros for use inside state handler functions ================== */

/* Designate the superstate. Used in the default case of a state handler
 * to indicate which state is the parent in the hierarchy. Also used
 * when responding to HSM_EMPTY_SIG. */
#define HSM_SUPER(superstate) \
    (me->temp = (HsmStateHandler)(superstate), HSM_RET_SUPER)

/* Take a state transition to 'target'. Sets the transition target and
 * returns the transition-taken code. */
#define HSM_TRAN(target) \
    (me->temp = (HsmStateHandler)(target), HSM_RET_TRAN)

/* Indicate that the event was handled (internal transition).
 * No state change occurs. */
#define HSM_HANDLED() HSM_RET_HANDLED

/* Indicate that the event was not handled due to a guard condition
 * failure. The engine should query this state for its superstate
 * and retry the event in the parent state. */
#define HSM_UNHANDLED() HSM_RET_UNHANDLED

#endif /* HSM_H */


#ifndef HSM_H
#define HSM_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/*============================================================================
 * Hierarchical State Machine (HSM) Engine
 *
 * States are represented as function pointers (HsmStateHandler). Each state
 * handler processes signals and returns a status code indicating how the
 * signal was processed.
 *
 * The state hierarchy is encoded implicitly: each state handler, when called
 * with HSM_SIG_EMPTY, sets me->temp to its superstate handler and returns
 * HSM_SUPER. The root of all hierarchies is hsm_top, which returns
 * HSM_IGNORED for all signals.
 *
 * Reserved signals:
 *   HSM_SIG_EMPTY (0) - Query superstate (handler sets me->temp, returns SUPER)
 *   HSM_SIG_ENTRY (1) - Enter state (handler runs entry action, returns HANDLED)
 *   HSM_SIG_EXIT  (2) - Exit state (handler runs exit action, returns HANDLED)
 *   HSM_SIG_INIT  (3) - Initial transition (handler may set me->temp to
 *                        initial substate target and return TRAN)
 *
 * Handler return values:
 *   HSM_SUPER      (0) - Event delegated to superstate (me->temp holds super)
 *   HSM_HANDLED    (1) - Event handled, no transition
 *   HSM_TRAN       (2) - Transition taken (me->temp holds target state)
 *   HSM_IGNORED    (3) - Event ignored (used only by hsm_top)
 *   HSM_UNHANDLED  (4) - Guard condition failed; propagate event upward
 *                         through hierarchy (same traversal as HSM_SUPER
 *                         but semantically distinct: the handler had a
 *                         matching transition whose guard evaluated false)
 *============================================================================*/

/* Maximum nesting depth of states (including top) */
#define HSM_MAX_NEST_DEPTH 8

/* Return values from state handlers */
#define HSM_SUPER      ((uint8_t)0)
#define HSM_HANDLED    ((uint8_t)1)
#define HSM_TRAN       ((uint8_t)2)
#define HSM_IGNORED    ((uint8_t)3)
#define HSM_UNHANDLED  ((uint8_t)4)

/* Reserved signals */
#define HSM_SIG_EMPTY ((int)0)
#define HSM_SIG_ENTRY ((int)1)
#define HSM_SIG_EXIT  ((int)2)
#define HSM_SIG_INIT  ((int)3)
#define HSM_SIG_USER  ((int)4)

typedef uint8_t HsmState;
typedef struct Hsm Hsm;
typedef HsmState (*HsmStateHandler)(Hsm *me, int sig);

struct Hsm {
    HsmStateHandler state;  /* current active (leaf) state */
    HsmStateHandler temp;   /* temp: superstate query result or transition target */
    char trace[8192];       /* trace buffer for recording actions */
    int trace_len;
};

/* Top state handler - root of all state hierarchies.
 * Returns HSM_IGNORED for all signals. */
HsmState hsm_top(Hsm *me, int sig);

/* Construct HSM: sets state to hsm_top, temp to initial pseudo-state handler */
void hsm_ctor(Hsm *me, HsmStateHandler initial);

/* Initialize: execute top-most initial transition and drill into target */
void hsm_init(Hsm *me);

/* Dispatch: process user signal through state hierarchy */
void hsm_dispatch(Hsm *me, int sig);

/* State containment query: returns true if the HSM is currently in 'state'
 * or any substate of 'state'. Must not alter observable HSM state — the
 * engine must function identically before and after this call. */
bool hsm_is_in(Hsm *me, HsmStateHandler state);

/* Get current trace string */
const char *hsm_trace(Hsm *me);

/* Clear trace buffer */
void hsm_trace_clear(Hsm *me);

/* Append string to trace buffer */
void hsm_trace_append(Hsm *me, const char *s);

/* Convenience macros for use inside state handlers */
#define HSM_TRAN_TO(me_, target_) \
    ((me_)->temp = (HsmStateHandler)(target_), (HsmState)HSM_TRAN)

#define HSM_SUPER_OF(me_, super_) \
    ((me_)->temp = (HsmStateHandler)(super_), (HsmState)HSM_SUPER)

#endif /* HSM_H */

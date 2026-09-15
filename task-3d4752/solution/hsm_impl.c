
/*
 * Complete HSM engine implementation.
 *
 * Implements: hsm_init(), hsm_dispatch(), hsm_is_in()
 */

#include "hsm.h"
#include <string.h>
#include <stdio.h>

/*============================================================================
 * Provided implementations
 *============================================================================*/

HsmState hsm_top(Hsm *me, int sig) {
    (void)me;
    (void)sig;
    return HSM_IGNORED;
}

void hsm_ctor(Hsm *me, HsmStateHandler initial) {
    me->state = hsm_top;
    me->temp = initial;
    me->trace[0] = '\0';
    me->trace_len = 0;
}

void hsm_trace_clear(Hsm *me) {
    me->trace[0] = '\0';
    me->trace_len = 0;
}

const char *hsm_trace(Hsm *me) {
    return me->trace;
}

void hsm_trace_append(Hsm *me, const char *s) {
    int len = (int)strlen(s);
    if (me->trace_len + len < (int)sizeof(me->trace) - 1) {
        memcpy(me->trace + me->trace_len, s, len);
        me->trace_len += len;
        me->trace[me->trace_len] = '\0';
    }
}

/*============================================================================
 * Internal helpers
 *============================================================================*/

/* Query a state's superstate by dispatching HSM_SIG_EMPTY */
static HsmStateHandler get_super(Hsm *me, HsmStateHandler s) {
    (*s)(me, HSM_SIG_EMPTY);
    return me->temp;
}

/* Build ancestor chain from state up to hsm_top (inclusive).
 * Returns number of entries stored. */
static int get_ancestors(Hsm *me, HsmStateHandler state,
                         HsmStateHandler *chain, int max) {
    int n = 0;
    HsmStateHandler s = state;
    while (n < max) {
        chain[n++] = s;
        if (s == hsm_top) break;
        s = get_super(me, s);
    }
    return n;
}

/* Find the Lowest Common Ancestor of source and target.
 * For self-transitions (source == target), returns the superstate. */
static HsmStateHandler find_lca(Hsm *me, HsmStateHandler source,
                                HsmStateHandler target) {
    if (source == target) {
        /* Self-transition: LCA is the superstate */
        return get_super(me, source);
    }

    HsmStateHandler s_chain[HSM_MAX_NEST_DEPTH];
    HsmStateHandler t_chain[HSM_MAX_NEST_DEPTH];
    int s_len = get_ancestors(me, source, s_chain, HSM_MAX_NEST_DEPTH);
    int t_len = get_ancestors(me, target, t_chain, HSM_MAX_NEST_DEPTH);

    /* Find the first (i.e., lowest/deepest) common ancestor */
    for (int i = 0; i < s_len; i++) {
        for (int j = 0; j < t_len; j++) {
            if (s_chain[i] == t_chain[j]) {
                return s_chain[i];
            }
        }
    }
    return hsm_top; /* fallback (should not happen in well-formed hierarchy) */
}

/* Exit states from 'from' up to 'lca' (not including lca). */
static void exit_to_lca(Hsm *me, HsmStateHandler from, HsmStateHandler lca) {
    HsmStateHandler s = from;
    while (s != lca) {
        (*s)(me, HSM_SIG_EXIT);
        s = get_super(me, s);
    }
}

/* Enter states from lca down to target (not including lca, including target).
 * Collects the path from target up to lca, then enters in reverse. */
static void enter_from_lca(Hsm *me, HsmStateHandler lca,
                           HsmStateHandler target) {
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];
    int depth = 0;
    HsmStateHandler s = target;
    while (s != lca && depth < HSM_MAX_NEST_DEPTH) {
        path[depth++] = s;
        s = get_super(me, s);
    }
    /* Enter in top-down order (reverse of collection order) */
    for (int i = depth - 1; i >= 0; i--) {
        (*path[i])(me, HSM_SIG_ENTRY);
    }
}

/* Drill into target via nested initial transitions.
 * Returns the final leaf state. */
static HsmStateHandler drill_into(Hsm *me, HsmStateHandler target) {
    HsmStateHandler t = target;
    while ((*t)(me, HSM_SIG_INIT) == HSM_TRAN) {
        HsmStateHandler new_target = me->temp;
        /* Collect entry path from new_target up to t */
        HsmStateHandler path[HSM_MAX_NEST_DEPTH];
        int depth = 0;
        HsmStateHandler s = new_target;
        while (s != t && depth < HSM_MAX_NEST_DEPTH) {
            path[depth++] = s;
            s = get_super(me, s);
        }
        /* Enter in top-down order */
        for (int i = depth - 1; i >= 0; i--) {
            (*path[i])(me, HSM_SIG_ENTRY);
        }
        t = new_target;
    }
    return t;
}

/*============================================================================
 * Public API
 *============================================================================*/

void hsm_init(Hsm *me) {
    /* Execute the initial pseudo-state handler */
    HsmStateHandler initial_handler = me->temp;
    (*initial_handler)(me, HSM_SIG_INIT);
    HsmStateHandler target = me->temp;

    /* Build entry path from target up to current state (hsm_top) */
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];
    int depth = 0;
    HsmStateHandler s = target;
    while (s != me->state && depth < HSM_MAX_NEST_DEPTH) {
        path[depth++] = s;
        s = get_super(me, s);
    }

    /* Enter in top-down order */
    for (int i = depth - 1; i >= 0; i--) {
        (*path[i])(me, HSM_SIG_ENTRY);
    }

    /* Drill into target via nested init transitions */
    me->state = drill_into(me, target);
}

void hsm_dispatch(Hsm *me, int sig) {
    HsmStateHandler s = me->state;

    /* Phase 1: Walk up the hierarchy to find a handler for the signal.
     * Record the path from current leaf to the handling state. */
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];
    int path_len = 0;
    HsmState r;

    do {
        path[path_len++] = s;
        r = (*s)(me, sig);
        if (r == HSM_UNHANDLED) {
            /* Guard condition failed: query superstate manually
             * (handler did not set me->temp) and continue search. */
            s = get_super(me, s);
            r = HSM_SUPER;
        } else if (r == HSM_SUPER) {
            s = me->temp; /* move to superstate */
        }
    } while (r == HSM_SUPER);

    /* If event was handled or ignored, no transition. */
    if (r == HSM_HANDLED || r == HSM_IGNORED) {
        return;
    }

    /* Phase 2: Transition (r == HSM_TRAN).
     * source = state that handled the event (last in path).
     * target = transition target (in me->temp, set by HSM_TRAN_TO). */
    HsmStateHandler source = path[path_len - 1];
    HsmStateHandler target = me->temp;

    /* Phase 3: Exit from current leaf up to source (not including source). */
    for (int i = 0; i < path_len - 1; i++) {
        (*path[i])(me, HSM_SIG_EXIT);
    }

    /* Phase 4: Compute LCA and execute transition. */
    HsmStateHandler lca = find_lca(me, source, target);
    exit_to_lca(me, source, lca);
    enter_from_lca(me, lca, target);

    /* Phase 5: Drill into target via nested init transitions. */
    me->state = drill_into(me, target);
}

bool hsm_is_in(Hsm *me, HsmStateHandler state) {
    bool found = false;
    HsmStateHandler s = me->state;

    /* Walk from current state toward top, checking for match */
    while (s != hsm_top) {
        if (s == state) {
            found = true;
            break;
        }
        s = get_super(me, s);
    }
    /* Check if asking about hsm_top itself */
    if (!found && state == hsm_top) {
        found = true;
    }

    /* Restore temp to current state to preserve engine invariant.
     * The hierarchy walk via HSM_SIG_EMPTY clobbers me->temp; leaving
     * it pointing at some ancestor could break a subsequent dispatch. */
    me->temp = me->state;

    return found;
}

/*
 * hsm_impl.c - Complete HSM Dispatch Engine Implementation
 *
 * Implements the UML hierarchical state machine dispatch algorithm with:
 * - Hierarchical event processing (bubble-up)
 * - LCA (Lowest Common Ancestor) based transitions
 * - Correct entry/exit action ordering
 * - Guard condition support (UNHANDLED bubbling)
 * - Nested initial transitions
 *
 */
#include "hsm.h"
#include <assert.h>

/* Reserved event instances for internal use */
static const HsmEvent hsm_reserved_events[4] = {
    { HSM_EMPTY_SIG },
    { HSM_ENTRY_SIG },
    { HSM_EXIT_SIG  },
    { HSM_INIT_SIG  }
};

/* Forward declarations of internal helpers */
static void   hsm_enter_target(Hsm *me, HsmStateHandler *path, size_t depth);
static size_t hsm_tran_simple(Hsm *me, HsmStateHandler *path);
static size_t hsm_tran_complex(Hsm *me, HsmStateHandler *path);

/* ================================================================== */

void hsm_ctor(Hsm *me, HsmStateHandler initial) {
    me->state = (HsmStateHandler)hsm_top;
    me->temp  = initial;
}

HsmRet hsm_top(Hsm *me, const HsmEvent *e) {
    (void)me;
    (void)e;
    return HSM_RET_IGNORED;
}

/* ================================================================== */

void hsm_init(Hsm *me, const HsmEvent *e) {
    HsmStateHandler s = me->state; /* must be hsm_top */
    assert(s == (HsmStateHandler)hsm_top);

    /* Execute the initial pseudostate handler */
    HsmRet r = (*me->temp)(me, e);
    assert(r == HSM_RET_TRAN);
    (void)r;

    /* Build entry path from target up to current config (top) */
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];
    size_t ip = 0;
    do {
        assert(ip < HSM_MAX_NEST_DEPTH);
        path[ip] = me->temp;
        ++ip;
        /* Query superstate of me->temp */
        (void)(*me->temp)(me, &hsm_reserved_events[HSM_EMPTY_SIG]);
    } while (me->temp != s);

    /* Enter states and drill down with nested initial transitions */
    hsm_enter_target(me, path, ip);

    me->state = path[0]; /* final current state */
}

/* ================================================================== */

void hsm_dispatch(Hsm *me, const HsmEvent *e) {
    HsmStateHandler s = me->state;
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];

    /* Phase 1: Bubble up - find a state that handles the event */
    me->temp = s;
    HsmRet r;
    size_t ip = HSM_MAX_NEST_DEPTH;

    do {
        assert(ip > 0);
        s = me->temp;
        --ip;
        path[ip] = s; /* record path from current state upward */

        r = (*s)(me, e); /* try to handle the event */

        if (r == HSM_RET_UNHANDLED) {
            /* Guard failed: query this state for its superstate */
            r = (*s)(me, &hsm_reserved_events[HSM_EMPTY_SIG]);
        }
    } while (r == HSM_RET_SUPER);

    /* Phase 2: Process the result */
    if (r == HSM_RET_HANDLED || r == HSM_RET_IGNORED) {
        /* Internal transition or event ignored: no state change */
        return;
    }

    assert(r == HSM_RET_TRAN);

    /* Transition taken: me->temp holds the target */
    path[0] = me->temp; /* save target */

    /* Exit from current state up to the transition source */
    for (size_t iq = HSM_MAX_NEST_DEPTH - 1; iq > ip; --iq) {
        (void)(*path[iq])(me, &hsm_reserved_events[HSM_EXIT_SIG]);
    }

    path[2] = s; /* save the transition source in path[2] */

    /* Phase 3: Execute the transition (find LCA, exit/enter) */
    size_t depth = hsm_tran_simple(me, path);
    if (depth > 1) {
        depth = hsm_tran_complex(me, path);
    }

    /* Phase 4: Enter target and drill down with initial transitions */
    hsm_enter_target(me, path, depth);

    me->state = path[0]; /* update current state */
}

/* ================================================================== */

/*
 * Enter states along the path from outermost to innermost,
 * then drill down with nested initial transitions.
 *
 * path[depth-1] is the outermost state to enter,
 * path[0] is the target (innermost).
 */
static void hsm_enter_target(Hsm *me, HsmStateHandler *path, size_t depth) {
    size_t ip = depth;

    /* Enter states from outermost to innermost */
    while (ip > 0) {
        --ip;
        (void)(*path[ip])(me, &hsm_reserved_events[HSM_ENTRY_SIG]);
    }

    HsmStateHandler t = path[0]; /* transition target */

    /* Drill down with nested initial transitions */
    while ((*t)(me, &hsm_reserved_events[HSM_INIT_SIG]) == HSM_RET_TRAN) {
        /* me->temp holds the new (deeper) target */

        /* Build entry path from new target up to t */
        ip = 0;
        do {
            assert(ip < HSM_MAX_NEST_DEPTH);
            path[ip] = me->temp;
            ++ip;
            (void)(*me->temp)(me, &hsm_reserved_events[HSM_EMPTY_SIG]);
        } while (me->temp != t);

        /* Enter from outermost to innermost */
        size_t iq = ip;
        while (iq > 0) {
            --iq;
            (void)(*path[iq])(me, &hsm_reserved_events[HSM_ENTRY_SIG]);
        }

        t = path[0]; /* new target for next iteration */
    }
}

/* ================================================================== */

/*
 * Try simple transition cases. Returns:
 *   0 — target is already active (don't enter it, but do run init)
 *   1 — enter path[0] (the target)
 *   2 — not a simple case; call hsm_tran_complex()
 *
 * On entry:
 *   path[0] = target
 *   path[2] = source
 *
 * On return (if < 2):
 *   path[0] = target, entry/exit actions already executed for simple cases
 */
static size_t hsm_tran_simple(Hsm *me, HsmStateHandler *path) {
    HsmStateHandler target = path[0];
    HsmStateHandler source = path[2];

    /* (a) Self-transition: source == target */
    if (source == target) {
        (void)(*source)(me, &hsm_reserved_events[HSM_EXIT_SIG]);
        return 1; /* re-enter target */
    }

    /* Find superstate of target */
    (void)(*target)(me, &hsm_reserved_events[HSM_EMPTY_SIG]);
    HsmStateHandler t = me->temp; /* target's superstate */

    /* (b) Source == target's super (source is parent of target) */
    if (source == t) {
        return 1; /* just enter target */
    }

    /* Find superstate of source */
    (void)(*source)(me, &hsm_reserved_events[HSM_EMPTY_SIG]);

    /* (c) Siblings: source->super == target->super */
    if (me->temp == t) {
        (void)(*source)(me, &hsm_reserved_events[HSM_EXIT_SIG]);
        return 1; /* enter target */
    }

    /* (d) Source's super == target (target is parent of source) */
    if (me->temp == target) {
        (void)(*source)(me, &hsm_reserved_events[HSM_EXIT_SIG]);
        return 0; /* don't enter target, but run its init */
    }

    /* Not a simple case. Save target->super for complex handler. */
    path[1] = t;   /* target's superstate */
    return 2;       /* caller must invoke hsm_tran_complex() */
}

/* ================================================================== */

/*
 * Handle complex transitions that require LCA finding.
 *
 * On entry:
 *   path[0] = target
 *   path[1] = target->super (set by hsm_tran_simple)
 *   path[2] = source
 *   me->temp = source->super (from hsm_tran_simple's last EMPTY call)
 *
 * Returns the number of states to enter (depth for hsm_enter_target).
 */
static size_t hsm_tran_complex(Hsm *me, HsmStateHandler *path) {
    HsmStateHandler source       = path[2];
    HsmStateHandler source_super = me->temp;       /* source->super */
    me->temp = path[1];                             /* target->super */

    /*
     * (e) Walk up from target->super, checking if source is an ancestor
     *     of the target. Build the entry path along the way.
     */
    size_t ip = 1;
    bool lca_found = false;
    HsmRet r;

    do {
        assert(ip < HSM_MAX_NEST_DEPTH);
        path[ip] = me->temp;
        ++ip;

        r = (*me->temp)(me, &hsm_reserved_events[HSM_EMPTY_SIG]);
        if (me->temp == source) {
            /* Source is an ancestor of target. LCA = source. */
            lca_found = true;
            break;
        }
    } while (r == HSM_RET_SUPER);

    if (!lca_found) {
        /*
         * (f) Exit source, then check if source->super is in the
         *     target's entry path.
         */
        (void)(*source)(me, &hsm_reserved_events[HSM_EXIT_SIG]);

        HsmStateHandler s = source_super;
        size_t iq = ip;
        while (iq > 0) {
            --iq;
            if (s == path[iq]) {
                ip = iq; /* don't enter the LCA */
                lca_found = true;
                break;
            }
        }

        if (!lca_found) {
            /*
             * (g) Walk up the source's ancestor chain. For each ancestor,
             *     exit it and check against the target's entry path.
             */
            for (;;) {
                /* Exit state s */
                if ((*s)(me, &hsm_reserved_events[HSM_EXIT_SIG])
                        == HSM_RET_HANDLED) {
                    /* EXIT was handled explicitly; need separate EMPTY
                     * to find the superstate. */
                    (void)(*s)(me, &hsm_reserved_events[HSM_EMPTY_SIG]);
                }
                s = me->temp; /* superstate of the exited state */

                /* Check s against the target's entry path */
                iq = ip;
                while (iq > 0) {
                    --iq;
                    if (s == path[iq]) {
                        ip = iq;
                        lca_found = true;
                        break;
                    }
                }
                if (lca_found) break;
            }
        }
    }

    return ip;
}

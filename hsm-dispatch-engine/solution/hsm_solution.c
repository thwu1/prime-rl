/*
 * HSM Engine — Reference Implementation
 *
 */

#include "hsm.h"

/*--------------------------------------------------------------------------*/
HsmState hsm_top(void *me, int sig) {
    (void)me;
    (void)sig;
    return HSM_RET_IGNORED;
}

/*--------------------------------------------------------------------------*/
void hsm_ctor(Hsm *me, HsmStateHandler initial) {
    me->state = &hsm_top;
    me->temp  = initial;
}

/*--------------------------------------------------------------------------*/
/* Helper: build ancestor chain from state up to (and including) hsm_top.   */
/* chain[0] = state, chain[n-1] = hsm_top.  Returns n.                     */
static size_t build_ancestors(Hsm *me, HsmStateHandler state,
                              HsmStateHandler chain[], size_t max) {
    size_t n = 0;
    HsmStateHandler s = state;
    while (n < max) {
        chain[n++] = s;
        if (s == &hsm_top) break;
        HsmState r = (*s)(me, HSM_SIG_EMPTY);
        if (r != HSM_RET_SUPER) break;
        s = me->temp;
    }
    return n;
}

/*--------------------------------------------------------------------------*/
/* Helper: enter states along path[] in top-down order, then drill into     */
/* nested initial transitions.  Returns final leaf state.                   */
static HsmStateHandler enter_and_drill(Hsm *me, HsmStateHandler target) {
    HsmStateHandler t = target;
    HsmStateHandler init_path[HSM_MAX_NEST_DEPTH];

    /* Drill into nested initial transitions */
    while ((*t)(me, HSM_SIG_INIT) == HSM_RET_TRAN) {
        /* me->temp holds the init sub-target */
        size_t ep = 0;
        do {
            init_path[ep] = me->temp;
            ++ep;
            (*me->temp)(me, HSM_SIG_EMPTY);
        } while (me->temp != t);

        /* Enter states top-down (from ep-1 to 0) */
        while (ep > 0U) {
            --ep;
            (*init_path[ep])(me, HSM_SIG_ENTRY);
        }
        t = init_path[0]; /* new target */
    }
    return t;
}

/*--------------------------------------------------------------------------*/
void hsm_init(Hsm *me) {
    HsmStateHandler s = me->state; /* should be hsm_top */

    /* 1. Execute top-most initial transition */
    (*me->temp)(me, 0);
    /* me->temp now holds the target state */

    /* 2. Build entry path from target up to current state (hsm_top) */
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];
    size_t ip = 0;
    do {
        path[ip] = me->temp;
        ++ip;
        (*me->temp)(me, HSM_SIG_EMPTY);
    } while (me->temp != s);

    /* 3. Enter states top-down */
    size_t k = ip;
    while (k > 0U) {
        --k;
        (*path[k])(me, HSM_SIG_ENTRY);
    }

    /* 4. Drill into nested initial transitions */
    HsmStateHandler t = enter_and_drill(me, path[0]);

    /* 5. Set final state */
    me->state = t;
}

/*--------------------------------------------------------------------------*/
void hsm_dispatch(Hsm *me, int sig) {
    HsmStateHandler cur = me->state;
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];

    /* === Phase 1: Hierarchical event handling === */
    me->temp = cur;
    HsmState r;
    HsmStateHandler s;
    size_t ip = HSM_MAX_NEST_DEPTH;
    do {
        s = me->temp;
        --ip;
        path[ip] = s;
        r = (*s)(me, sig);
        if (r == HSM_RET_UNHANDLED) {
            r = (*s)(me, HSM_SIG_EMPTY); /* find superstate */
        }
    } while (r == HSM_RET_SUPER);

    /* === Phase 2: No transition === */
    if (r == HSM_RET_HANDLED || r == HSM_RET_IGNORED) {
        return;
    }

    /* === Phase 3: Transition (r == HSM_RET_TRAN) === */
    HsmStateHandler target = me->temp;
    HsmStateHandler source = s; /* the handler that took the transition */

    /* 3a. Exit from current state down to (not including) source */
    for (size_t iq = HSM_MAX_NEST_DEPTH - 1U; iq > ip; --iq) {
        (*path[iq])(me, HSM_SIG_EXIT);
    }

    /* 3b. Handle self-transition specially */
    if (source == target) {
        (*source)(me, HSM_SIG_EXIT);
        (*target)(me, HSM_SIG_ENTRY);
    }
    else {
        /* 3c. Build ancestor chains and find LCA */
        HsmStateHandler src_chain[HSM_MAX_NEST_DEPTH + 1];
        HsmStateHandler tgt_chain[HSM_MAX_NEST_DEPTH + 1];
        size_t src_n = build_ancestors(me, source,
                                       src_chain, HSM_MAX_NEST_DEPTH + 1);
        size_t tgt_n = build_ancestors(me, target,
                                       tgt_chain, HSM_MAX_NEST_DEPTH + 1);

        /* Both chains end at hsm_top. Walk backwards to find divergence. */
        size_t si = src_n - 1U;
        size_t ti = tgt_n - 1U;
        while (si > 0U && ti > 0U
               && src_chain[si - 1U] == tgt_chain[ti - 1U]) {
            --si;
            --ti;
        }
        /* LCA = src_chain[si] = tgt_chain[ti] */

        /* Exit from source up to (not including) LCA */
        for (size_t i = 0U; i < si; i++) {
            (*src_chain[i])(me, HSM_SIG_EXIT);
        }

        /* Enter from just below LCA down to target (top-down) */
        for (size_t i = ti; i > 0U; --i) {
            (*tgt_chain[i - 1U])(me, HSM_SIG_ENTRY);
        }
    }

    /* 3d. Drill into initial transitions */
    HsmStateHandler t = enter_and_drill(me, target);

    /* 3e. Update current state */
    me->state = t;
}

"""
Generate the correct HSM dispatch engine implementation.

This script programmatically constructs hsm.c by building the source code
from its constituent algorithmic components. Each function is generated
based on the UML Statechart specification for hierarchical state machines.

"""

import textwrap

# Build the implementation from algorithmic components

HEADER = '''\
#include "hsm.h"
'''

TOP_STATE = '''\
HsmState hsm_top(void *me, int sig) {
    (void)me;
    (void)sig;
    return HSM_RET_IGNORED;
}
'''

CONSTRUCTOR = '''\
void hsm_ctor(Hsm *me, HsmStateHandler initial) {
    me->state = &hsm_top;
    me->temp  = initial;
}
'''

# Helper: build ancestor chain [state, parent, ..., hsm_top]
ANCESTOR_HELPER = '''\
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
'''

# Helper: drill into nested initial transitions
DRILL_HELPER = '''\
static HsmStateHandler enter_and_drill(Hsm *me, HsmStateHandler target) {
    HsmStateHandler t = target;
    HsmStateHandler init_path[HSM_MAX_NEST_DEPTH];
    while ((*t)(me, HSM_SIG_INIT) == HSM_RET_TRAN) {
        size_t ep = 0;
        do {
            init_path[ep] = me->temp;
            ++ep;
            (*me->temp)(me, HSM_SIG_EMPTY);
        } while (me->temp != t);
        while (ep > 0U) {
            --ep;
            (*init_path[ep])(me, HSM_SIG_ENTRY);
        }
        t = init_path[0];
    }
    return t;
}
'''

# hsm_init: execute top-most initial transition, enter target hierarchy
INIT_FUNC = '''\
void hsm_init(Hsm *me) {
    HsmStateHandler s = me->state;
    (*me->temp)(me, 0);
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];
    size_t ip = 0;
    do {
        path[ip] = me->temp;
        ++ip;
        (*me->temp)(me, HSM_SIG_EMPTY);
    } while (me->temp != s);
    size_t k = ip;
    while (k > 0U) {
        --k;
        (*path[k])(me, HSM_SIG_ENTRY);
    }
    me->state = enter_and_drill(me, path[0]);
}
'''

# hsm_dispatch: hierarchical event dispatch with LCA-based transitions
DISPATCH_FUNC = '''\
void hsm_dispatch(Hsm *me, int sig) {
    HsmStateHandler cur = me->state;
    HsmStateHandler path[HSM_MAX_NEST_DEPTH];
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
            r = (*s)(me, HSM_SIG_EMPTY);
        }
    } while (r == HSM_RET_SUPER);
    if (r == HSM_RET_HANDLED || r == HSM_RET_IGNORED) {
        return;
    }
    HsmStateHandler target = me->temp;
    HsmStateHandler source = s;
    for (size_t iq = HSM_MAX_NEST_DEPTH - 1U; iq > ip; --iq) {
        (*path[iq])(me, HSM_SIG_EXIT);
    }
    if (source == target) {
        (*source)(me, HSM_SIG_EXIT);
        (*target)(me, HSM_SIG_ENTRY);
    } else {
        HsmStateHandler src_chain[HSM_MAX_NEST_DEPTH + 1];
        HsmStateHandler tgt_chain[HSM_MAX_NEST_DEPTH + 1];
        size_t src_n = build_ancestors(me, source,
                                       src_chain, HSM_MAX_NEST_DEPTH + 1);
        size_t tgt_n = build_ancestors(me, target,
                                       tgt_chain, HSM_MAX_NEST_DEPTH + 1);
        size_t si = src_n - 1U;
        size_t ti = tgt_n - 1U;
        while (si > 0U && ti > 0U
               && src_chain[si - 1U] == tgt_chain[ti - 1U]) {
            --si;
            --ti;
        }
        for (size_t i = 0U; i < si; i++) {
            (*src_chain[i])(me, HSM_SIG_EXIT);
        }
        for (size_t i = ti; i > 0U; --i) {
            (*tgt_chain[i - 1U])(me, HSM_SIG_ENTRY);
        }
    }
    me->state = enter_and_drill(me, target);
}
'''

# Assemble the complete source file
components = [
    HEADER,
    TOP_STATE,
    CONSTRUCTOR,
    ANCESTOR_HELPER,
    DRILL_HELPER,
    INIT_FUNC,
    DISPATCH_FUNC,
]

source = "\n".join(components)

with open("/app/hsm.c", "w") as f:
    f.write(source)

print("Generated /app/hsm.c successfully.")

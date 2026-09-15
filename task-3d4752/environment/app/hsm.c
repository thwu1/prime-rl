
#include "hsm.h"
#include <string.h>
#include <stdio.h>

/*============================================================================
 * Provided implementations - DO NOT MODIFY
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
 * YOUR IMPLEMENTATION BELOW
 *============================================================================*/

void hsm_init(Hsm *me) {
    /* YOUR IMPLEMENTATION HERE */
}

void hsm_dispatch(Hsm *me, int sig) {
    /* YOUR IMPLEMENTATION HERE */
}

bool hsm_is_in(Hsm *me, HsmStateHandler state) {
    /* YOUR IMPLEMENTATION HERE */
    (void)me;
    (void)state;
    return false;
}

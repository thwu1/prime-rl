/*
 * QHsmTst — State handler implementations.
 *
 * State hierarchy:
 *
 *   hsm_top
 *     └── s
 *           ├── s1
 *           │     └── s11
 *           └── s2
 *                 └── s21
 *                       └── s211
 *
 * Initial transitions:
 *   top  --> s2    (qhsmtst_initial)
 *   s    --> s11   (s handles HSM_SIG_INIT)
 *   s1   --> s11   (s1 handles HSM_SIG_INIT)
 *   s2   --> s211  (s2 handles HSM_SIG_INIT)
 *   s21  --> s211  (s21 handles HSM_SIG_INIT)
 *
 */

#include "hsm.h"
#include "qhsmtst.h"
#include "trace.h"

/* The single global instance */
QHsmTst the_hsm;

/* Forward declarations of all state handlers */
static HsmState qhsmtst_initial(void *me, int sig);
static HsmState qhsmtst_s(void *me, int sig);
static HsmState qhsmtst_s1(void *me, int sig);
static HsmState qhsmtst_s11(void *me, int sig);
static HsmState qhsmtst_s2(void *me, int sig);
static HsmState qhsmtst_s21(void *me, int sig);
static HsmState qhsmtst_s211(void *me, int sig);

/*--------------------------------------------------------------------------*/
void qhsmtst_ctor(void) {
    hsm_ctor(&the_hsm.super, &qhsmtst_initial);
}

/*--------------------------------------------------------------------------*/
/* Initial pseudo-state handler                                             */
static HsmState qhsmtst_initial(void *me, int sig) {
    QHsmTst *m = (QHsmTst *)me;
    (void)sig;
    m->foo = 0U;
    BSP_display("top-INIT;");
    return HSM_TRAN(&qhsmtst_s2);
}

/*--------------------------------------------------------------------------*/
/* State s — top-level composite state (parent: hsm_top)                    */
static HsmState qhsmtst_s(void *me, int sig) {
    QHsmTst *m = (QHsmTst *)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            BSP_display("s-ENTRY;");
            return HSM_HANDLED();
        case HSM_SIG_EXIT:
            BSP_display("s-EXIT;");
            return HSM_HANDLED();
        case HSM_SIG_INIT:
            BSP_display("s-INIT;");
            return HSM_TRAN(&qhsmtst_s11);
        case I_SIG:
            if (m->foo) {
                m->foo = 0U;
                BSP_display("s-I;");
                return HSM_HANDLED();
            }
            return HSM_UNHANDLED();
        case E_SIG:
            BSP_display("s-E;");
            return HSM_TRAN(&qhsmtst_s11);
        default:
            return HSM_SUPER(&hsm_top);
    }
}

/*--------------------------------------------------------------------------*/
/* State s1 (parent: s)                                                     */
static HsmState qhsmtst_s1(void *me, int sig) {
    QHsmTst *m = (QHsmTst *)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            BSP_display("s1-ENTRY;");
            return HSM_HANDLED();
        case HSM_SIG_EXIT:
            BSP_display("s1-EXIT;");
            return HSM_HANDLED();
        case HSM_SIG_INIT:
            BSP_display("s1-INIT;");
            return HSM_TRAN(&qhsmtst_s11);
        case I_SIG:
            BSP_display("s1-I;");
            return HSM_HANDLED();
        case D_SIG:
            if (!m->foo) {
                m->foo = 1U;
                BSP_display("s1-D;");
                return HSM_TRAN(&qhsmtst_s);
            }
            return HSM_UNHANDLED();
        case A_SIG:
            BSP_display("s1-A;");
            return HSM_TRAN(&qhsmtst_s1);
        case B_SIG:
            BSP_display("s1-B;");
            return HSM_TRAN(&qhsmtst_s11);
        case F_SIG:
            BSP_display("s1-F;");
            return HSM_TRAN(&qhsmtst_s211);
        case C_SIG:
            BSP_display("s1-C;");
            return HSM_TRAN(&qhsmtst_s2);
        default:
            return HSM_SUPER(&qhsmtst_s);
    }
}

/*--------------------------------------------------------------------------*/
/* State s11 — leaf state (parent: s1)                                      */
static HsmState qhsmtst_s11(void *me, int sig) {
    QHsmTst *m = (QHsmTst *)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            BSP_display("s11-ENTRY;");
            return HSM_HANDLED();
        case HSM_SIG_EXIT:
            BSP_display("s11-EXIT;");
            return HSM_HANDLED();
        case H_SIG:
            BSP_display("s11-H;");
            return HSM_TRAN(&qhsmtst_s);
        case D_SIG:
            if (m->foo) {
                m->foo = 0U;
                BSP_display("s11-D;");
                return HSM_TRAN(&qhsmtst_s1);
            }
            return HSM_UNHANDLED();
        case G_SIG:
            BSP_display("s11-G;");
            return HSM_TRAN(&qhsmtst_s211);
        default:
            return HSM_SUPER(&qhsmtst_s1);
    }
}

/*--------------------------------------------------------------------------*/
/* State s2 (parent: s)                                                     */
static HsmState qhsmtst_s2(void *me, int sig) {
    QHsmTst *m = (QHsmTst *)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            BSP_display("s2-ENTRY;");
            return HSM_HANDLED();
        case HSM_SIG_EXIT:
            BSP_display("s2-EXIT;");
            return HSM_HANDLED();
        case HSM_SIG_INIT:
            BSP_display("s2-INIT;");
            return HSM_TRAN(&qhsmtst_s211);
        case I_SIG:
            if (!m->foo) {
                m->foo = 1U;
                BSP_display("s2-I;");
                return HSM_HANDLED();
            }
            return HSM_UNHANDLED();
        case F_SIG:
            BSP_display("s2-F;");
            return HSM_TRAN(&qhsmtst_s11);
        case C_SIG:
            BSP_display("s2-C;");
            return HSM_TRAN(&qhsmtst_s1);
        default:
            return HSM_SUPER(&qhsmtst_s);
    }
}

/*--------------------------------------------------------------------------*/
/* State s21 (parent: s2)                                                   */
static HsmState qhsmtst_s21(void *me, int sig) {
    (void)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            BSP_display("s21-ENTRY;");
            return HSM_HANDLED();
        case HSM_SIG_EXIT:
            BSP_display("s21-EXIT;");
            return HSM_HANDLED();
        case HSM_SIG_INIT:
            BSP_display("s21-INIT;");
            return HSM_TRAN(&qhsmtst_s211);
        case G_SIG:
            BSP_display("s21-G;");
            return HSM_TRAN(&qhsmtst_s1);
        case A_SIG:
            BSP_display("s21-A;");
            return HSM_TRAN(&qhsmtst_s21);
        case B_SIG:
            BSP_display("s21-B;");
            return HSM_TRAN(&qhsmtst_s211);
        default:
            return HSM_SUPER(&qhsmtst_s2);
    }
}

/*--------------------------------------------------------------------------*/
/* State s211 — leaf state (parent: s21)                                    */
static HsmState qhsmtst_s211(void *me, int sig) {
    (void)me;
    switch (sig) {
        case HSM_SIG_ENTRY:
            BSP_display("s211-ENTRY;");
            return HSM_HANDLED();
        case HSM_SIG_EXIT:
            BSP_display("s211-EXIT;");
            return HSM_HANDLED();
        case H_SIG:
            BSP_display("s211-H;");
            return HSM_TRAN(&qhsmtst_s);
        case D_SIG:
            BSP_display("s211-D;");
            return HSM_TRAN(&qhsmtst_s21);
        default:
            return HSM_SUPER(&qhsmtst_s21);
    }
}

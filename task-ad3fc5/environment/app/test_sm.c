/*
 * test_sm.c - Test State Machine Implementation
 *
 * Implements the hierarchical state machine defined in test_sm.h.
 * Each state handler logs its actions via printf for trace verification.
 *
 * State Hierarchy:
 *              top
 *               |
 *               r        (init -> r1)
 *             /   \
 *           r1     r2    (init -> r211)
 *          / \      \
 *        r11  r12   r21  (init -> r211)
 *                    |
 *                  r211
 *
 * Signal Handling Summary:
 *   P: self-transition (r1->r1, r21->r21)
 *   Q: parent-to-child (r1->r11, r21->r211)
 *   R: cross-hierarchy (r1->r2, r2->r1, r12->r21)
 *   S: guarded child-to-parent (r211->r21, r11->r1[foo], r1->r[!foo])
 *   T: ancestor-to-descendant (r->r11)
 *   U: deep cross (r1->r211, r2->r11)
 *   V: cross (r11->r211, r12->r211, r21->r1)
 *   W: various (r11<->r12, r211->r)
 *   X: internal/guarded (r1:handled, r2:[!foo], r:[foo])
 */

#include "test_sm.h"
#include <stdio.h>

/* Forward declarations of state handlers */
static HsmRet TestSM_initial(Hsm *me, const HsmEvent *e);
static HsmRet TestSM_r(Hsm *me, const HsmEvent *e);
static HsmRet TestSM_r1(Hsm *me, const HsmEvent *e);
static HsmRet TestSM_r11(Hsm *me, const HsmEvent *e);
static HsmRet TestSM_r12(Hsm *me, const HsmEvent *e);
static HsmRet TestSM_r2(Hsm *me, const HsmEvent *e);
static HsmRet TestSM_r21(Hsm *me, const HsmEvent *e);
static HsmRet TestSM_r211(Hsm *me, const HsmEvent *e);

/* Global instance */
TestSM test_sm;

void TestSM_ctor(TestSM *me) {
    hsm_ctor(&me->super, (HsmStateHandler)&TestSM_initial);
    me->foo = 0;
}

const char *TestSM_state_name(TestSM *me) {
    HsmStateHandler s = me->super.state;
    if (s == (HsmStateHandler)&TestSM_r)    return "r";
    if (s == (HsmStateHandler)&TestSM_r1)   return "r1";
    if (s == (HsmStateHandler)&TestSM_r11)  return "r11";
    if (s == (HsmStateHandler)&TestSM_r12)  return "r12";
    if (s == (HsmStateHandler)&TestSM_r2)   return "r2";
    if (s == (HsmStateHandler)&TestSM_r21)  return "r21";
    if (s == (HsmStateHandler)&TestSM_r211) return "r211";
    if (s == (HsmStateHandler)&hsm_top)     return "top";
    return "unknown";
}

uint8_t TestSM_get_foo(TestSM *me) {
    return me->foo;
}

/* ===== Initial Pseudostate ============================================ */

static HsmRet TestSM_initial(Hsm *me, const HsmEvent *e) {
    TestSM *self = (TestSM *)me;
    (void)e;
    self->foo = 0;
    printf("top-INIT;");
    return HSM_TRAN(TestSM_r2);
}

/* ===== State: r (superstate: top) ===================================== */

static HsmRet TestSM_r(Hsm *me, const HsmEvent *e) {
    TestSM *self = (TestSM *)me;
    switch (e->sig) {
        case HSM_ENTRY_SIG:
            printf("r-ENTRY;");
            return HSM_HANDLED();
        case HSM_EXIT_SIG:
            printf("r-EXIT;");
            return HSM_HANDLED();
        case HSM_INIT_SIG:
            printf("r-INIT;");
            return HSM_TRAN(TestSM_r1);
        case T_SIG:
            printf("r-T;");
            return HSM_TRAN(TestSM_r11);
        case X_SIG:
            if (self->foo) {
                self->foo = 0;
                printf("r-X;");
                return HSM_HANDLED();
            }
            return HSM_UNHANDLED();
        default:
            return HSM_SUPER(hsm_top);
    }
}

/* ===== State: r1 (superstate: r) ====================================== */

static HsmRet TestSM_r1(Hsm *me, const HsmEvent *e) {
    TestSM *self = (TestSM *)me;
    switch (e->sig) {
        case HSM_ENTRY_SIG:
            printf("r1-ENTRY;");
            return HSM_HANDLED();
        case HSM_EXIT_SIG:
            printf("r1-EXIT;");
            return HSM_HANDLED();
        case HSM_INIT_SIG:
            printf("r1-INIT;");
            return HSM_TRAN(TestSM_r11);
        case P_SIG:
            printf("r1-P;");
            return HSM_TRAN(TestSM_r1);  /* self-transition */
        case Q_SIG:
            printf("r1-Q;");
            return HSM_TRAN(TestSM_r11);
        case R_SIG:
            printf("r1-R;");
            return HSM_TRAN(TestSM_r2);
        case S_SIG:
            if (!self->foo) {
                self->foo = 1;
                printf("r1-S;");
                return HSM_TRAN(TestSM_r);
            }
            return HSM_UNHANDLED();
        case U_SIG:
            printf("r1-U;");
            return HSM_TRAN(TestSM_r211);
        case X_SIG:
            printf("r1-X;");
            return HSM_HANDLED();
        default:
            return HSM_SUPER(TestSM_r);
    }
}

/* ===== State: r11 (superstate: r1) ==================================== */

static HsmRet TestSM_r11(Hsm *me, const HsmEvent *e) {
    TestSM *self = (TestSM *)me;
    switch (e->sig) {
        case HSM_ENTRY_SIG:
            printf("r11-ENTRY;");
            return HSM_HANDLED();
        case HSM_EXIT_SIG:
            printf("r11-EXIT;");
            return HSM_HANDLED();
        case S_SIG:
            if (self->foo) {
                self->foo = 0;
                printf("r11-S;");
                return HSM_TRAN(TestSM_r1);
            }
            return HSM_UNHANDLED();
        case V_SIG:
            printf("r11-V;");
            return HSM_TRAN(TestSM_r211);
        case W_SIG:
            printf("r11-W;");
            return HSM_TRAN(TestSM_r12);
        default:
            return HSM_SUPER(TestSM_r1);
    }
}

/* ===== State: r12 (superstate: r1) ==================================== */

static HsmRet TestSM_r12(Hsm *me, const HsmEvent *e) {
    (void)me;
    switch (e->sig) {
        case HSM_ENTRY_SIG:
            printf("r12-ENTRY;");
            return HSM_HANDLED();
        case HSM_EXIT_SIG:
            printf("r12-EXIT;");
            return HSM_HANDLED();
        case R_SIG:
            printf("r12-R;");
            return HSM_TRAN(TestSM_r21);
        case V_SIG:
            printf("r12-V;");
            return HSM_TRAN(TestSM_r211);
        case W_SIG:
            printf("r12-W;");
            return HSM_TRAN(TestSM_r11);
        default:
            return HSM_SUPER(TestSM_r1);
    }
}

/* ===== State: r2 (superstate: r) ====================================== */

static HsmRet TestSM_r2(Hsm *me, const HsmEvent *e) {
    TestSM *self = (TestSM *)me;
    switch (e->sig) {
        case HSM_ENTRY_SIG:
            printf("r2-ENTRY;");
            return HSM_HANDLED();
        case HSM_EXIT_SIG:
            printf("r2-EXIT;");
            return HSM_HANDLED();
        case HSM_INIT_SIG:
            printf("r2-INIT;");
            return HSM_TRAN(TestSM_r211);
        case R_SIG:
            printf("r2-R;");
            return HSM_TRAN(TestSM_r1);
        case U_SIG:
            printf("r2-U;");
            return HSM_TRAN(TestSM_r11);
        case X_SIG:
            if (!self->foo) {
                self->foo = 1;
                printf("r2-X;");
                return HSM_HANDLED();
            }
            return HSM_UNHANDLED();
        default:
            return HSM_SUPER(TestSM_r);
    }
}

/* ===== State: r21 (superstate: r2) ==================================== */

static HsmRet TestSM_r21(Hsm *me, const HsmEvent *e) {
    (void)me;
    switch (e->sig) {
        case HSM_ENTRY_SIG:
            printf("r21-ENTRY;");
            return HSM_HANDLED();
        case HSM_EXIT_SIG:
            printf("r21-EXIT;");
            return HSM_HANDLED();
        case HSM_INIT_SIG:
            printf("r21-INIT;");
            return HSM_TRAN(TestSM_r211);
        case P_SIG:
            printf("r21-P;");
            return HSM_TRAN(TestSM_r21);  /* self-transition */
        case Q_SIG:
            printf("r21-Q;");
            return HSM_TRAN(TestSM_r211);
        case V_SIG:
            printf("r21-V;");
            return HSM_TRAN(TestSM_r1);
        default:
            return HSM_SUPER(TestSM_r2);
    }
}

/* ===== State: r211 (superstate: r21) ================================== */

static HsmRet TestSM_r211(Hsm *me, const HsmEvent *e) {
    (void)me;
    switch (e->sig) {
        case HSM_ENTRY_SIG:
            printf("r211-ENTRY;");
            return HSM_HANDLED();
        case HSM_EXIT_SIG:
            printf("r211-EXIT;");
            return HSM_HANDLED();
        case S_SIG:
            printf("r211-S;");
            return HSM_TRAN(TestSM_r21);
        case W_SIG:
            printf("r211-W;");
            return HSM_TRAN(TestSM_r);
        default:
            return HSM_SUPER(TestSM_r21);
    }
}

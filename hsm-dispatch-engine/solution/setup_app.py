"""
Backup script that ensures all necessary source files exist in /app/.
This handles the case where the Docker COPY didn't work correctly.

"""

import os

os.makedirs("/app", exist_ok=True)

FILES = {}

FILES["Makefile"] = """\
CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -O2
SRCS = main.c hsm.c qhsmtst.c trace.c
OBJS = $(SRCS:.c=.o)
TARGET = qhsmtst

all: $(TARGET)

$(TARGET): $(OBJS)
\t$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
\t$(CC) $(CFLAGS) -c -o $@ $<

clean:
\trm -f $(OBJS) $(TARGET)

.PHONY: all clean
"""

FILES["hsm.h"] = """\
#ifndef HSM_H
#define HSM_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

typedef uint_fast8_t HsmState;

#define HSM_RET_HANDLED   ((HsmState)0U)
#define HSM_RET_IGNORED   ((HsmState)1U)
#define HSM_RET_SUPER     ((HsmState)2U)
#define HSM_RET_TRAN      ((HsmState)3U)
#define HSM_RET_UNHANDLED ((HsmState)4U)

#define HSM_SIG_EMPTY  0
#define HSM_SIG_ENTRY  1
#define HSM_SIG_EXIT   2
#define HSM_SIG_INIT   3
#define HSM_SIG_USER   4

#define HSM_MAX_NEST_DEPTH 6

typedef HsmState (*HsmStateHandler)(void *me, int sig);

typedef struct {
    HsmStateHandler state;
    HsmStateHandler temp;
} Hsm;

#define HSM_TRAN(target_) \\
    (((Hsm *)(me))->temp = (HsmStateHandler)(target_), HSM_RET_TRAN)

#define HSM_SUPER(super_) \\
    (((Hsm *)(me))->temp = (HsmStateHandler)(super_), HSM_RET_SUPER)

#define HSM_HANDLED()   (HSM_RET_HANDLED)

#define HSM_UNHANDLED() (HSM_RET_UNHANDLED)

HsmState hsm_top(void *me, int sig);

void hsm_ctor(Hsm *me, HsmStateHandler initial);
void hsm_init(Hsm *me);
void hsm_dispatch(Hsm *me, int sig);

#endif /* HSM_H */
"""

FILES["qhsmtst.h"] = """\
#ifndef QHSMTST_H
#define QHSMTST_H

#include "hsm.h"

enum QHsmTstSignals {
    A_SIG = HSM_SIG_USER,
    B_SIG,
    C_SIG,
    D_SIG,
    E_SIG,
    F_SIG,
    G_SIG,
    H_SIG,
    I_SIG,
    MAX_SIG
};

typedef struct {
    Hsm super;
    uint8_t foo;
} QHsmTst;

extern QHsmTst the_hsm;

void qhsmtst_ctor(void);

#endif /* QHSMTST_H */
"""

FILES["trace.h"] = """\
#ifndef TRACE_H
#define TRACE_H

#define TRACE_BUF_SIZE 4096

extern char trace_buf[];

void BSP_display(const char *msg);
void trace_clear(void);
const char *trace_get(void);

#endif /* TRACE_H */
"""

FILES["trace.c"] = """\
#include "trace.h"
#include <string.h>

char trace_buf[TRACE_BUF_SIZE];

void BSP_display(const char *msg) {
    size_t cur = strlen(trace_buf);
    size_t rem = TRACE_BUF_SIZE - cur - 1;
    size_t len = strlen(msg);
    if (len > rem) len = rem;
    memcpy(trace_buf + cur, msg, len);
    trace_buf[cur + len] = '\\0';
}

void trace_clear(void) {
    trace_buf[0] = '\\0';
}

const char *trace_get(void) {
    return trace_buf;
}
"""

FILES["main.c"] = """\
#include <stdio.h>
#include "hsm.h"
#include "qhsmtst.h"
#include "trace.h"

int main(void) {
    qhsmtst_ctor();

    trace_clear();
    hsm_init(&the_hsm.super);
    printf("INIT: %s\\n", trace_get());

    static const struct { int sig; const char *name; } events[] = {
        { G_SIG, "G" },
        { I_SIG, "I" },
        { A_SIG, "A" },
        { D_SIG, "D" },
        { D_SIG, "D" },
        { C_SIG, "C" },
        { F_SIG, "F" },
        { F_SIG, "F" },
        { E_SIG, "E" },
        { H_SIG, "H" },
        { B_SIG, "B" },
        { G_SIG, "G" },
        { I_SIG, "I" },
        { I_SIG, "I" },
        { H_SIG, "H" },
        { C_SIG, "C" },
        { B_SIG, "B" },
        { D_SIG, "D" },
    };
    int n = (int)(sizeof(events) / sizeof(events[0]));

    for (int i = 0; i < n; i++) {
        trace_clear();
        hsm_dispatch(&the_hsm.super, events[i].sig);
        printf("Signal %s: %s\\n", events[i].name, trace_get());
    }

    return 0;
}
"""

FILES["qhsmtst.c"] = """\
#include "hsm.h"
#include "qhsmtst.h"
#include "trace.h"

QHsmTst the_hsm;

static HsmState qhsmtst_initial(void *me, int sig);
static HsmState qhsmtst_s(void *me, int sig);
static HsmState qhsmtst_s1(void *me, int sig);
static HsmState qhsmtst_s11(void *me, int sig);
static HsmState qhsmtst_s2(void *me, int sig);
static HsmState qhsmtst_s21(void *me, int sig);
static HsmState qhsmtst_s211(void *me, int sig);

void qhsmtst_ctor(void) {
    hsm_ctor(&the_hsm.super, &qhsmtst_initial);
}

static HsmState qhsmtst_initial(void *me, int sig) {
    QHsmTst *m = (QHsmTst *)me;
    (void)sig;
    m->foo = 0U;
    BSP_display("top-INIT;");
    return HSM_TRAN(&qhsmtst_s2);
}

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
"""

for name, content in FILES.items():
    path = os.path.join("/app", name)
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {path}")

print("App source files restored successfully.")

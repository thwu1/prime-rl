#!/usr/bin/env python3
"""
Generate the mark-compact GC versions of vm.h and vm.c.

This script transforms the mark-sweep VM into a LISP2 mark-compact VM
by rewriting vm.h (Object struct, VM struct) and vm.c (allocation, GC).
"""

VM_H = r'''/*
 * vm.h - Simple object VM with NaN-boxed values and mark-compact GC
 *
 * Values use NaN boxing: a 64-bit IEEE 754 double encodes numbers directly,
 * while non-number types (nil, booleans, object pointers) are packed into
 * the mantissa bits of quiet NaN representations.
 *
 * Object types: OBJ_INT (boxed integer), OBJ_PAIR (cons cell with two Values).
 * GC algorithm: LISP2 mark-compact with contiguous heap.
 */

#ifndef VM_H
#define VM_H

#include <stdint.h>
#include <string.h>

/* ===================== NaN Boxing ===================== */

typedef uint64_t Value;

#define SIGN_BIT ((uint64_t)0x8000000000000000)
#define QNAN     ((uint64_t)0x7ffc000000000000)

#define TAG_NIL   1
#define TAG_FALSE 2
#define TAG_TRUE  3

/* Type checking */
#define IS_NUMBER(value)  (((value) & QNAN) != QNAN)
#define IS_NIL(value)     ((value) == NIL_VAL)
#define IS_BOOL(value)    (((value) | 1) == TRUE_VAL)
#define IS_OBJ(value)     (((value) & (QNAN | SIGN_BIT)) == (QNAN | SIGN_BIT))

/* Value constructors */
#define NIL_VAL           ((Value)(uint64_t)(QNAN | TAG_NIL))
#define FALSE_VAL         ((Value)(uint64_t)(QNAN | TAG_FALSE))
#define TRUE_VAL          ((Value)(uint64_t)(QNAN | TAG_TRUE))
#define BOOL_VAL(b)       ((b) ? TRUE_VAL : FALSE_VAL)
#define OBJ_VAL(obj)      ((Value)(SIGN_BIT | QNAN | (uint64_t)(uintptr_t)(obj)))

/* Value extraction */
#define AS_BOOL(value)    ((value) == TRUE_VAL)
#define AS_OBJ(value)     ((Object*)(uintptr_t)((value) & ~(SIGN_BIT | QNAN)))

static inline double valueToNum(Value value) {
    double num;
    memcpy(&num, &value, sizeof(Value));
    return num;
}

static inline Value numToValue(double num) {
    Value value;
    memcpy(&value, &num, sizeof(double));
    return value;
}

#define NUMBER_VAL(num)   numToValue(num)
#define AS_NUMBER(value)  valueToNum(value)

/* ===================== Objects ===================== */

typedef enum {
    OBJ_INT,
    OBJ_PAIR
} ObjectType;

typedef struct sObject {
    ObjectType type;
    unsigned char marked;
    struct sObject* forwardingAddr;  /* Used during mark-compact GC */
    union {
        int intValue;           /* OBJ_INT payload */
        struct {
            Value head;         /* OBJ_PAIR first element (NaN-boxed) */
            Value tail;         /* OBJ_PAIR second element (NaN-boxed) */
        };
    };
} Object;

/* ===================== Virtual Machine ===================== */

#define STACK_MAX 256
#define HEAP_SIZE 1024

typedef struct {
    Value stack[STACK_MAX];
    int stackSize;

    Object heap[HEAP_SIZE];     /* Contiguous object heap */
    int heapUsed;               /* Bump-pointer index (next free slot) */
    int gcThreshold;            /* GC trigger threshold */
} VM;

/* Public API */
VM*   newVM(void);
void  freeVM(VM* vm);

void  push(VM* vm, Value value);
Value pop(VM* vm);
Value peek(VM* vm, int distance);

void  pushInt(VM* vm, int intValue);
void  pushPair(VM* vm);

void  gc(VM* vm);

void  printValue(Value value);
void  printObject(Object* obj);

#endif /* VM_H */
'''

VM_C = r'''/*
 * vm.c - VM implementation with LISP2 mark-compact garbage collection
 *
 * Memory model:
 *   Objects are allocated from a contiguous heap array via bump allocation.
 *   The GC uses the LISP2 mark-compact algorithm to eliminate fragmentation.
 *
 * GC algorithm (LISP2 mark-compact, 4 phases):
 *   1. MARK                - Recursively mark reachable objects from roots.
 *   2. CALCULATE ADDRESSES - Walk heap, assign forwarding addresses to live objects.
 *   3. UPDATE REFERENCES   - Rewrite all pointers (NaN-boxed!) to use new addresses.
 *   4. COMPACT             - Move objects to their forwarding addresses.
 */

#include "vm.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define INIT_GC_THRESHOLD 8

/* ===================== VM lifecycle ===================== */

VM* newVM(void) {
    VM* vm = (VM*)malloc(sizeof(VM));
    vm->stackSize    = 0;
    vm->heapUsed     = 0;
    vm->gcThreshold  = INIT_GC_THRESHOLD;
    return vm;
}

void freeVM(VM* vm) {
    free(vm);
}

/* ===================== Stack operations ===================== */

void push(VM* vm, Value value) {
    if (vm->stackSize >= STACK_MAX) {
        fprintf(stderr, "Stack overflow\n");
        exit(1);
    }
    vm->stack[vm->stackSize++] = value;
}

Value pop(VM* vm) {
    if (vm->stackSize <= 0) {
        fprintf(stderr, "Stack underflow\n");
        exit(1);
    }
    return vm->stack[--vm->stackSize];
}

Value peek(VM* vm, int distance) {
    return vm->stack[vm->stackSize - 1 - distance];
}

/* ===================== Printing ===================== */

void printObject(Object* obj) {
    switch (obj->type) {
        case OBJ_INT:
            printf("Int(%d)", obj->intValue);
            break;
        case OBJ_PAIR:
            printf("Pair(");
            printValue(obj->head);
            printf(", ");
            printValue(obj->tail);
            printf(")");
            break;
    }
}

void printValue(Value value) {
    if (IS_NUMBER(value)) {
        printf("%g", AS_NUMBER(value));
    } else if (IS_NIL(value)) {
        printf("nil");
    } else if (IS_BOOL(value)) {
        printf(AS_BOOL(value) ? "true" : "false");
    } else if (IS_OBJ(value)) {
        printObject(AS_OBJ(value));
    }
}

/* ===================== Object allocation ===================== */

static Object* newObject(VM* vm, ObjectType type) {
    if (vm->heapUsed >= vm->gcThreshold) {
        gc(vm);
    }
    if (vm->heapUsed >= HEAP_SIZE) {
        fprintf(stderr, "Out of memory\n");
        exit(1);
    }

    Object* obj      = &vm->heap[vm->heapUsed++];
    obj->type           = type;
    obj->marked         = 0;
    obj->forwardingAddr = NULL;
    return obj;
}

void pushInt(VM* vm, int intValue) {
    Object* obj   = newObject(vm, OBJ_INT);
    obj->intValue = intValue;
    push(vm, OBJ_VAL(obj));
}

void pushPair(VM* vm) {
    Object* obj = newObject(vm, OBJ_PAIR);
    obj->tail   = pop(vm);
    obj->head   = pop(vm);
    push(vm, OBJ_VAL(obj));
}

/* ===================== Phase 1: Mark ===================== */

static void markObject(Object* obj);

static void markValue(Value value) {
    if (IS_OBJ(value)) {
        markObject(AS_OBJ(value));
    }
}

static void markObject(Object* obj) {
    if (obj == NULL || obj->marked) return;
    obj->marked = 1;

    if (obj->type == OBJ_PAIR) {
        markValue(obj->head);
        markValue(obj->tail);
    }
}

static void markAll(VM* vm) {
    for (int i = 0; i < vm->stackSize; i++) {
        markValue(vm->stack[i]);
    }
}

/* ===================== Phase 2: Calculate forwarding addresses ===================== */

static void calculateNewAddresses(VM* vm) {
    int dest = 0;
    for (int i = 0; i < vm->heapUsed; i++) {
        if (vm->heap[i].marked) {
            vm->heap[i].forwardingAddr = &vm->heap[dest];
            dest++;
        }
    }
}

/* ===================== Phase 3: Update references ===================== */

/*
 * Given a NaN-boxed Value, if it encodes an object pointer, decode it,
 * look up the object's forwarding address, and re-encode as a new
 * NaN-boxed pointer. Non-object Values (numbers, nil, bools) pass through.
 */
static Value updateValue(Value value) {
    if (IS_OBJ(value)) {
        Object* obj = AS_OBJ(value);
        if (obj->forwardingAddr != NULL) {
            return OBJ_VAL(obj->forwardingAddr);
        }
    }
    return value;
}

static void updateAllReferences(VM* vm) {
    /* Update the stack (root set). */
    for (int i = 0; i < vm->stackSize; i++) {
        vm->stack[i] = updateValue(vm->stack[i]);
    }

    /* Update fields inside live objects. */
    for (int i = 0; i < vm->heapUsed; i++) {
        if (vm->heap[i].marked && vm->heap[i].type == OBJ_PAIR) {
            vm->heap[i].head = updateValue(vm->heap[i].head);
            vm->heap[i].tail = updateValue(vm->heap[i].tail);
        }
    }
}

/* ===================== Phase 4: Compact ===================== */

static void compact(VM* vm) {
    int newUsed = 0;
    for (int i = 0; i < vm->heapUsed; i++) {
        if (vm->heap[i].marked) {
            Object* dest = vm->heap[i].forwardingAddr;
            if (dest != &vm->heap[i]) {
                memmove(dest, &vm->heap[i], sizeof(Object));
            }
            dest->marked         = 0;
            dest->forwardingAddr = NULL;
            newUsed++;
        }
    }
    vm->heapUsed = newUsed;
}

/* ===================== GC entry point ===================== */

void gc(VM* vm) {
    markAll(vm);
    calculateNewAddresses(vm);
    updateAllReferences(vm);
    compact(vm);

    vm->gcThreshold = vm->heapUsed == 0
                      ? INIT_GC_THRESHOLD
                      : vm->heapUsed * 2;
    if (vm->gcThreshold > HEAP_SIZE) {
        vm->gcThreshold = HEAP_SIZE;
    }
}
'''


def main():
    with open("/app/vm.h", "w") as f:
        f.write(VM_H)
    print("Wrote /app/vm.h (mark-compact version)")

    with open("/app/vm.c", "w") as f:
        f.write(VM_C)
    print("Wrote /app/vm.c (mark-compact version)")


if __name__ == "__main__":
    main()

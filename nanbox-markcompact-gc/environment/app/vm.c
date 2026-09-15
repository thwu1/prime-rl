/*
 * vm.c - VM implementation with mark-sweep garbage collection
 *
 * Memory model:
 *   Each Object is individually malloc'd and linked into a singly-linked list
 *   rooted at vm->firstObject. The GC walks this list during the sweep phase
 *   to free unreachable objects.
 *
 * GC algorithm (mark-sweep):
 *   1. MARK  - Starting from roots (the VM stack), recursively mark every
 *              reachable object.
 *   2. SWEEP - Walk the all-objects list; free any object whose mark bit
 *              is clear, then clear the mark bit on survivors.
 */

#include "vm.h"
#include <stdio.h>
#include <stdlib.h>

#define INIT_GC_THRESHOLD 8

/* ===================== VM lifecycle ===================== */

VM* newVM(void) {
    VM* vm = (VM*)malloc(sizeof(VM));
    vm->stackSize   = 0;
    vm->firstObject = NULL;
    vm->numObjects  = 0;
    vm->maxObjects  = INIT_GC_THRESHOLD;
    return vm;
}

void freeVM(VM* vm) {
    /* Walk the linked list and free every object. */
    Object* obj = vm->firstObject;
    while (obj) {
        Object* next = obj->next;
        free(obj);
        obj = next;
    }
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
    if (vm->numObjects >= vm->maxObjects) {
        gc(vm);
    }

    Object* obj  = (Object*)malloc(sizeof(Object));
    obj->type    = type;
    obj->marked  = 0;
    obj->next    = vm->firstObject;
    vm->firstObject = obj;
    vm->numObjects++;
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

/* ===================== Mark phase ===================== */

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

/* ===================== Sweep phase ===================== */

static void sweep(VM* vm) {
    Object** slot = &vm->firstObject;
    while (*slot) {
        if (!(*slot)->marked) {
            Object* garbage = *slot;
            *slot = garbage->next;
            free(garbage);
            vm->numObjects--;
        } else {
            (*slot)->marked = 0;
            slot = &(*slot)->next;
        }
    }
}

/* ===================== GC entry point ===================== */

void gc(VM* vm) {
    markAll(vm);
    sweep(vm);

    vm->maxObjects = vm->numObjects == 0
                     ? INIT_GC_THRESHOLD
                     : vm->numObjects * 2;
}

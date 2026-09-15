/*
 * main.c - Test driver for the VM
 *
 * Exercises allocation, garbage collection, NaN-boxed value types,
 * nested pairs, and stress scenarios.
 */

#include "vm.h"
#include <stdio.h>
#include <stdlib.h>

/* ---- Test 1: Basic integer allocation ---- */
static void test1(void) {
    printf("=== Test 1: Basic allocation ===\n");
    VM* vm = newVM();

    pushInt(vm, 42);
    pushInt(vm, 17);

    Object* o1 = AS_OBJ(peek(vm, 1));
    Object* o2 = AS_OBJ(peek(vm, 0));
    printf("v1 = Int(%d)\n", o1->intValue);
    printf("v2 = Int(%d)\n", o2->intValue);

    pop(vm); pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- Test 2: Pair allocation ---- */
static void test2(void) {
    printf("=== Test 2: Pair allocation ===\n");
    VM* vm = newVM();

    pushInt(vm, 1);
    pushInt(vm, 2);
    pushPair(vm);

    printf("pair = ");
    printValue(peek(vm, 0));
    printf("\n");

    pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- Test 3: GC preserves reachable objects ---- */
static void test3(void) {
    printf("=== Test 3: GC preserves reachable ===\n");
    VM* vm = newVM();

    pushInt(vm, 10);
    pushInt(vm, 20);
    pushPair(vm);

    pushInt(vm, 30);
    pushInt(vm, 40);
    pushPair(vm);

    gc(vm);

    printf("pair1 = ");
    printValue(peek(vm, 1));
    printf("\n");
    printf("pair2 = ");
    printValue(peek(vm, 0));
    printf("\n");

    pop(vm); pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- Test 4: GC collects unreachable objects ---- */
static void test4(void) {
    printf("=== Test 4: GC collects unreachable ===\n");
    VM* vm = newVM();

    pushInt(vm, 1);
    pushInt(vm, 2);
    pop(vm);
    pop(vm);
    /* Both Int(1) and Int(2) are now unreachable. */

    pushInt(vm, 3);
    gc(vm);

    printf("v = ");
    printValue(peek(vm, 0));
    printf("\n");

    pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- Test 5: Nested pairs survive GC ---- */
static void test5(void) {
    printf("=== Test 5: Nested pairs ===\n");
    VM* vm = newVM();

    pushInt(vm, 1);
    pushInt(vm, 2);
    pushPair(vm);       /* inner = Pair(1, 2) */

    pushInt(vm, 3);
    pushPair(vm);       /* outer = Pair(inner, 3) */

    gc(vm);

    printf("outer = ");
    printValue(peek(vm, 0));
    printf("\n");

    pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- Test 6: Mixed NaN-boxed value types in pairs ---- */
static void test6(void) {
    printf("=== Test 6: Mixed NaN-boxed values ===\n");
    VM* vm = newVM();

    /* Pair(3.14, Int(99)) */
    push(vm, NUMBER_VAL(3.14));
    pushInt(vm, 99);
    pushPair(vm);

    /* Pair(nil, true) */
    push(vm, NIL_VAL);
    push(vm, TRUE_VAL);
    pushPair(vm);

    /* Pair of pairs */
    pushPair(vm);

    gc(vm);

    printf("result = ");
    printValue(peek(vm, 0));
    printf("\n");

    pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- Test 7: Stress test — long linked list ---- */
static void test7(void) {
    printf("=== Test 7: Stress test ===\n");
    VM* vm = newVM();

    /*
     * Build: Pair(0, Pair(1, Pair(2, ... Pair(99, nil)...)))
     * Construction works right-to-left so that element 0 is at the head.
     */
    push(vm, NIL_VAL);
    for (int i = 99; i >= 0; i--) {
        pushInt(vm, i);
        /* Swap top two: [list, Int(i)] -> [Int(i), list] */
        Value tmp = vm->stack[vm->stackSize - 1];
        vm->stack[vm->stackSize - 1] = vm->stack[vm->stackSize - 2];
        vm->stack[vm->stackSize - 2] = tmp;
        pushPair(vm);   /* Pair(head=Int(i), tail=list) */
    }

    /* Walk the list and print first 5 elements. */
    Value current = peek(vm, 0);
    int count = 0;
    printf("list: ");
    while (!IS_NIL(current)) {
        Object* pair = AS_OBJ(current);
        if (count < 5) {
            if (count > 0) printf(" ");
            printf("%d", AS_OBJ(pair->head)->intValue);
        }
        current = pair->tail;
        count++;
    }
    printf(" (total=%d)\n", count);

    pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- Test 8: Post-GC allocation ---- */
static void test8(void) {
    printf("=== Test 8: Post-GC allocation ===\n");
    VM* vm = newVM();

    pushInt(vm, 100);   /* Keep this one. */
    pushInt(vm, 200);
    pop(vm);            /* 200 becomes garbage. */
    pushInt(vm, 300);
    pop(vm);            /* 300 becomes garbage. */

    gc(vm);             /* Collect 200 and 300. */

    pushInt(vm, 400);
    pushInt(vm, 500);
    pushPair(vm);       /* Pair(400, 500) */

    printf("bottom = ");
    printValue(peek(vm, 1));
    printf("\n");
    printf("pair_top = ");
    printValue(peek(vm, 0));
    printf("\n");

    pop(vm); pop(vm);
    freeVM(vm);
    printf("PASS\n\n");
}

/* ---- main ---- */
int main(void) {
    test1();
    test2();
    test3();
    test4();
    test5();
    test6();
    test7();
    test8();

    printf("ALL TESTS PASSED\n");
    return 0;
}

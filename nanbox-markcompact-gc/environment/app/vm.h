/*
 * vm.h - Simple object VM with NaN-boxed values and garbage collection
 *
 * Values use NaN boxing: a 64-bit IEEE 754 double encodes numbers directly,
 * while non-number types (nil, booleans, object pointers) are packed into
 * the mantissa bits of quiet NaN representations.
 *
 * Object types: OBJ_INT (boxed integer), OBJ_PAIR (cons cell with two Values).
 * GC algorithm: mark-sweep with malloc-based allocation.
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
    struct sObject* next;       /* Intrusive linked list for GC traversal */
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

typedef struct {
    Value stack[STACK_MAX];
    int stackSize;

    Object* firstObject;        /* Head of all-objects linked list */
    int numObjects;             /* Current live object count */
    int maxObjects;             /* GC trigger threshold */
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

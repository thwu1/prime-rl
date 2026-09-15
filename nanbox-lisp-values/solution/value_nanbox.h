#ifndef VALUE_H
#define VALUE_H

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

/*
 * NaN-boxing: every Value is a single uint64_t (8 bytes).
 *
 * IEEE 754 double:  if (v & QNAN) != QNAN  ->  it is a plain double.
 *
 * Tagged values live inside the quiet-NaN space:
 *
 *   QNAN  = 0x7FFC000000000000   (exponent 0x7FF, quiet bit, marker bit 50)
 *
 *   Singletons (bit 63 = 0, low payload):
 *     nil   = QNAN | 1
 *     false = QNAN | 2
 *     true  = QNAN | 3
 *
 *   Integer (bit 63 = 0, bits 49-48 = 01, bits 31-0 = int32 payload):
 *     QNAN | (1 << 48) | (uint32_t)(int32_t)n
 *
 *   Pointer types (bit 63 = 1, bits 49-48 = subtype, bits 47-0 = address):
 *     SIGN_BIT | QNAN | (subtype << 48) | (ptr & 0x0000FFFFFFFFFFFF)
 *     subtype 0 = string   (char *)
 *     subtype 1 = symbol   (char *)
 *     subtype 2 = cons     (Cons *)
 *     subtype 3 = builtin  (BuiltinFn)
 */

typedef uint64_t Value;

#define QNAN       ((uint64_t)0x7FFC000000000000ULL)
#define SIGN_BIT   ((uint64_t)0x8000000000000000ULL)
#define PTR_MASK   ((uint64_t)0x0000FFFFFFFFFFFFULL)

#define TAG_NIL    ((uint64_t)1)
#define TAG_FALSE  ((uint64_t)2)
#define TAG_TRUE   ((uint64_t)3)
#define INT_TAG    ((uint64_t)1 << 48)

#define PTAG_STRING  ((uint64_t)0 << 48)
#define PTAG_SYMBOL  ((uint64_t)1 << 48)
#define PTAG_CONS    ((uint64_t)2 << 48)
#define PTAG_BUILTIN ((uint64_t)3 << 48)

/* ValueType enum kept for switch()-based dispatch */
typedef enum {
    VAL_NIL = 0,
    VAL_BOOL,
    VAL_INT,
    VAL_FLOAT,
    VAL_STRING,
    VAL_SYMBOL,
    VAL_CONS,
    VAL_BUILTIN,
} ValueType;

/* Forward-declare Cons; defined after Value is complete */
struct Cons;

typedef Value (*BuiltinFn)(Value *args, int nargs);

typedef struct Cons {
    Value car;
    Value cdr;
} Cons;

/* ---- double <-> bits helpers ---- */

static inline Value _d2b(double d) {
    uint64_t b; memcpy(&b, &d, 8); return b;
}
static inline double _b2d(Value v) {
    double d; memcpy(&d, &v, 8); return d;
}

/* ---- Constructors ---- */

static inline Value val_nil(void)    { return QNAN | TAG_NIL; }
static inline Value val_bool(bool b) { return b ? (QNAN | TAG_TRUE)
                                                : (QNAN | TAG_FALSE); }

static inline Value val_int(int64_t n) {
    return QNAN | INT_TAG | (uint64_t)(uint32_t)(int32_t)n;
}

static inline Value val_float(double d) {
    if (isnan(d)) return (uint64_t)0x7FF8000000000000ULL; /* canonical NaN */
    return _d2b(d);
}

static inline Value val_string(char *s) {
    return SIGN_BIT | QNAN | PTAG_STRING | ((uint64_t)(uintptr_t)s & PTR_MASK);
}
static inline Value val_symbol(char *s) {
    return SIGN_BIT | QNAN | PTAG_SYMBOL | ((uint64_t)(uintptr_t)s & PTR_MASK);
}

Value val_cons(Value car, Value cdr); /* allocates — defined in value.c */

static inline Value val_builtin(BuiltinFn fn) {
    return SIGN_BIT | QNAN | PTAG_BUILTIN | ((uint64_t)(uintptr_t)fn & PTR_MASK);
}

/* ---- Type predicates ---- */

static inline bool is_float(Value v)   { return (v & QNAN) != QNAN; }
static inline bool is_nil(Value v)     { return v == (QNAN | TAG_NIL); }
static inline bool is_bool(Value v)    { return v == (QNAN | TAG_TRUE) ||
                                                v == (QNAN | TAG_FALSE); }
static inline bool is_int(Value v)     { return (v & 0xFFFF000000000000ULL)
                                                == 0x7FFD000000000000ULL; }
static inline bool is_number(Value v)  { return is_int(v) || is_float(v); }
static inline bool is_string(Value v)  { return (v >> 48) == 0xFFFC; }
static inline bool is_symbol(Value v)  { return (v >> 48) == 0xFFFD; }
static inline bool is_cons(Value v)    { return (v >> 48) == 0xFFFE; }
static inline bool is_builtin(Value v) { return (v >> 48) == 0xFFFF; }

/* ---- Accessors ---- */

static inline bool      val_get_bool(Value v)    { return v == (QNAN | TAG_TRUE); }
static inline int32_t   val_get_int(Value v)     { return (int32_t)(uint32_t)v; }
static inline double    val_get_float(Value v)   { return _b2d(v); }
static inline char     *val_get_string(Value v)  { return (char *)(uintptr_t)(v & PTR_MASK); }
static inline char     *val_get_symbol(Value v)  { return (char *)(uintptr_t)(v & PTR_MASK); }
static inline Cons     *val_get_cons(Value v)    { return (Cons *)(uintptr_t)(v & PTR_MASK); }
static inline BuiltinFn val_get_builtin(Value v) { return (BuiltinFn)(uintptr_t)(v & PTR_MASK); }

/* ---- Utility (implemented in value.c) ---- */

ValueType   value_type(Value v);
double      val_to_double(Value v);
void        val_print(Value v, FILE *out);
void        val_println(Value v, FILE *out);
bool        val_equal(Value a, Value b);
bool        val_truthy(Value v);
const char *val_type_name(Value v);

#endif

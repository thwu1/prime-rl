#ifndef VALUE_H
#define VALUE_H

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>

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

/* Forward-declare so Value can hold a Cons pointer */
struct Cons;

typedef struct Value Value;
typedef Value (*BuiltinFn)(Value *args, int nargs);

struct Value {
    ValueType type;
    union {
        int64_t integer;
        double floating;
        bool boolean;
        char *string;
        char *symbol;
        struct Cons *cons;
        BuiltinFn builtin;
    } as;
};

/* Now Cons can hold Value by value */
typedef struct Cons {
    Value car;
    Value cdr;
} Cons;

/* Constructors */
Value val_nil(void);
Value val_bool(bool b);
Value val_int(int64_t n);
Value val_float(double d);
Value val_string(char *s);
Value val_symbol(char *s);
Value val_cons(Value car, Value cdr);
Value val_builtin(BuiltinFn fn);

/* Type predicates — note: these access v.type directly */
static inline bool is_nil(Value v)     { return v.type == VAL_NIL; }
static inline bool is_bool(Value v)    { return v.type == VAL_BOOL; }
static inline bool is_int(Value v)     { return v.type == VAL_INT; }
static inline bool is_float(Value v)   { return v.type == VAL_FLOAT; }
static inline bool is_number(Value v)  { return v.type == VAL_INT || v.type == VAL_FLOAT; }
static inline bool is_string(Value v)  { return v.type == VAL_STRING; }
static inline bool is_symbol(Value v)  { return v.type == VAL_SYMBOL; }
static inline bool is_cons(Value v)    { return v.type == VAL_CONS; }
static inline bool is_builtin(Value v) { return v.type == VAL_BUILTIN; }

/* Utility */
double val_to_double(Value v);
void val_print(Value v, FILE *out);
void val_println(Value v, FILE *out);
bool val_equal(Value a, Value b);
bool val_truthy(Value v);
const char *val_type_name(Value v);

#endif

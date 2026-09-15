/* ChocoPy C Runtime Library */

#ifndef CHPY_RUNTIME_H
#define CHPY_RUNTIME_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

typedef enum {
    CHPY_NONE = 0,
    CHPY_INT,
    CHPY_BOOL,
    CHPY_STR,
    CHPY_LIST,
    CHPY_OBJ
} ChpyType;

typedef struct ChpyVal ChpyVal;
typedef ChpyVal* (*ChpyFuncPtr)(int nargs, ChpyVal** args);

typedef struct {
    const char* class_name;
    ChpyFuncPtr* vtable;
    int nmethods;
    ChpyVal** attrs;
    int nattrs;
} ChpyObjData;

struct ChpyVal {
    ChpyType type;
    union {
        int ival;
        int bval;
        char* sval;
        struct {
            ChpyVal** elems;
            int len;
        } list;
        ChpyObjData obj;
    } d;
};

/* Singleton None */
ChpyVal* chpy_none(void);

/* Constructors */
ChpyVal* chpy_int(int v);
ChpyVal* chpy_bool(int v);
ChpyVal* chpy_str(const char* s);
ChpyVal* chpy_new_list(int n, ...);
ChpyVal* chpy_empty_list(void);
ChpyVal* chpy_new_obj(const char* cls, ChpyFuncPtr* vtable,
                       int nmethods, int nattrs, ...);

/* Arithmetic */
ChpyVal* chpy_add(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_sub(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_mul(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_div(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_mod(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_neg(ChpyVal* a);

/* Comparisons */
ChpyVal* chpy_eq(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_neq(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_lt(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_lte(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_gt(ChpyVal* a, ChpyVal* b);
ChpyVal* chpy_gte(ChpyVal* a, ChpyVal* b);

/* Logical */
ChpyVal* chpy_not(ChpyVal* a);
int chpy_is_true(ChpyVal* a);
ChpyVal* chpy_is_op(ChpyVal* a, ChpyVal* b);

/* Subscript */
ChpyVal* chpy_index(ChpyVal* obj, ChpyVal* idx);
void chpy_index_set(ChpyVal* obj, ChpyVal* idx, ChpyVal* val);

/* Attributes */
ChpyVal* chpy_get_attr(ChpyVal* obj, int idx);
void chpy_set_attr(ChpyVal* obj, int idx, ChpyVal* val);

/* Method dispatch */
ChpyVal* chpy_call_method(ChpyVal* obj, int method_idx,
                           int nargs, ChpyVal** args);

/* Iteration */
int chpy_iter_len(ChpyVal* obj);
ChpyVal* chpy_iter_get(ChpyVal* obj, int i);

/* Built-ins */
ChpyVal* chpy_print(ChpyVal* v);
ChpyVal* chpy_len(ChpyVal* v);

/* Runtime errors */
void chpy_err_divzero(void);
void chpy_err_index(void);
void chpy_err_none(void);

#endif

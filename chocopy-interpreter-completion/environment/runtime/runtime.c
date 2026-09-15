/* ChocoPy C Runtime Library — Implementation */

#include "runtime.h"

/* Portable string duplication (pure C99, no POSIX strdup needed). */
static char* chpy_dupstr(const char* s) {
    size_t n = strlen(s) + 1;
    char* d = (char*)malloc(n);
    if (d) memcpy(d, s, n);
    return d;
}

static ChpyVal _none_singleton = { .type = CHPY_NONE };

ChpyVal* chpy_none(void) {
    return &_none_singleton;
}

ChpyVal* chpy_int(int v) {
    ChpyVal* val = (ChpyVal*)malloc(sizeof(ChpyVal));
    val->type = CHPY_INT;
    val->d.ival = v;
    return val;
}

ChpyVal* chpy_bool(int v) {
    ChpyVal* val = (ChpyVal*)malloc(sizeof(ChpyVal));
    val->type = CHPY_BOOL;
    val->d.bval = v ? 1 : 0;
    return val;
}

ChpyVal* chpy_str(const char* s) {
    ChpyVal* val = (ChpyVal*)malloc(sizeof(ChpyVal));
    val->type = CHPY_STR;
    val->d.sval = chpy_dupstr(s);
    return val;
}

ChpyVal* chpy_new_list(int n, ...) {
    ChpyVal* val = (ChpyVal*)malloc(sizeof(ChpyVal));
    val->type = CHPY_LIST;
    val->d.list.len = n;
    if (n > 0) {
        val->d.list.elems = (ChpyVal**)malloc(sizeof(ChpyVal*) * n);
        va_list ap;
        va_start(ap, n);
        for (int i = 0; i < n; i++) {
            val->d.list.elems[i] = va_arg(ap, ChpyVal*);
        }
        va_end(ap);
    } else {
        val->d.list.elems = NULL;
    }
    return val;
}

ChpyVal* chpy_empty_list(void) {
    ChpyVal* val = (ChpyVal*)malloc(sizeof(ChpyVal));
    val->type = CHPY_LIST;
    val->d.list.len = 0;
    val->d.list.elems = NULL;
    return val;
}

ChpyVal* chpy_new_obj(const char* cls, ChpyFuncPtr* vtable,
                       int nmethods, int nattrs, ...) {
    ChpyVal* val = (ChpyVal*)malloc(sizeof(ChpyVal));
    val->type = CHPY_OBJ;
    val->d.obj.class_name = cls;
    val->d.obj.vtable = vtable;
    val->d.obj.nmethods = nmethods;
    val->d.obj.nattrs = nattrs;
    if (nattrs > 0) {
        val->d.obj.attrs = (ChpyVal**)malloc(sizeof(ChpyVal*) * nattrs);
        va_list ap;
        va_start(ap, nattrs);
        for (int i = 0; i < nattrs; i++) {
            val->d.obj.attrs[i] = va_arg(ap, ChpyVal*);
        }
        va_end(ap);
    } else {
        val->d.obj.attrs = NULL;
    }
    return val;
}

/* ---- Arithmetic ---- */

ChpyVal* chpy_add(ChpyVal* a, ChpyVal* b) {
    if (a->type == CHPY_INT && b->type == CHPY_INT)
        return chpy_int(a->d.ival + b->d.ival);
    if (a->type == CHPY_STR && b->type == CHPY_STR) {
        size_t la = strlen(a->d.sval), lb = strlen(b->d.sval);
        char* buf = (char*)malloc(la + lb + 1);
        memcpy(buf, a->d.sval, la);
        memcpy(buf + la, b->d.sval, lb + 1);
        ChpyVal* r = (ChpyVal*)malloc(sizeof(ChpyVal));
        r->type = CHPY_STR;
        r->d.sval = buf;
        return r;
    }
    if (a->type == CHPY_LIST && b->type == CHPY_LIST) {
        int total = a->d.list.len + b->d.list.len;
        ChpyVal* r = (ChpyVal*)malloc(sizeof(ChpyVal));
        r->type = CHPY_LIST;
        r->d.list.len = total;
        r->d.list.elems = (ChpyVal**)malloc(sizeof(ChpyVal*) * total);
        for (int i = 0; i < a->d.list.len; i++)
            r->d.list.elems[i] = a->d.list.elems[i];
        for (int i = 0; i < b->d.list.len; i++)
            r->d.list.elems[a->d.list.len + i] = b->d.list.elems[i];
        return r;
    }
    fprintf(stderr, "Unsupported operation\n");
    exit(6);
}

ChpyVal* chpy_sub(ChpyVal* a, ChpyVal* b) {
    return chpy_int(a->d.ival - b->d.ival);
}

ChpyVal* chpy_mul(ChpyVal* a, ChpyVal* b) {
    return chpy_int(a->d.ival * b->d.ival);
}

ChpyVal* chpy_div(ChpyVal* a, ChpyVal* b) {
    if (b->d.ival == 0) chpy_err_divzero();
    int ai = a->d.ival, bi = b->d.ival;
    int q = ai / bi;
    int r = ai - q * bi;
    if (r != 0 && ((r ^ bi) < 0)) q--;
    return chpy_int(q);
}

ChpyVal* chpy_mod(ChpyVal* a, ChpyVal* b) {
    if (b->d.ival == 0) chpy_err_divzero();
    int ai = a->d.ival, bi = b->d.ival;
    int r = ai % bi;
    if (r != 0 && ((r ^ bi) < 0)) r += bi;
    return chpy_int(r);
}

ChpyVal* chpy_neg(ChpyVal* a) {
    return chpy_int(-a->d.ival);
}

/* ---- Comparisons ---- */

ChpyVal* chpy_eq(ChpyVal* a, ChpyVal* b) {
    if (a->type == CHPY_INT && b->type == CHPY_INT)
        return chpy_bool(a->d.ival == b->d.ival);
    if (a->type == CHPY_BOOL && b->type == CHPY_BOOL)
        return chpy_bool(a->d.bval == b->d.bval);
    if (a->type == CHPY_STR && b->type == CHPY_STR)
        return chpy_bool(strcmp(a->d.sval, b->d.sval) == 0);
    return chpy_bool(0);
}

ChpyVal* chpy_neq(ChpyVal* a, ChpyVal* b) {
    ChpyVal* eq = chpy_eq(a, b);
    return chpy_bool(!eq->d.bval);
}

ChpyVal* chpy_lt(ChpyVal* a, ChpyVal* b) {
    return chpy_bool(a->d.ival < b->d.ival);
}

ChpyVal* chpy_lte(ChpyVal* a, ChpyVal* b) {
    return chpy_bool(a->d.ival <= b->d.ival);
}

ChpyVal* chpy_gt(ChpyVal* a, ChpyVal* b) {
    return chpy_bool(a->d.ival > b->d.ival);
}

ChpyVal* chpy_gte(ChpyVal* a, ChpyVal* b) {
    return chpy_bool(a->d.ival >= b->d.ival);
}

/* ---- Logical ---- */

ChpyVal* chpy_not(ChpyVal* a) {
    return chpy_bool(!a->d.bval);
}

int chpy_is_true(ChpyVal* a) {
    return (a->type == CHPY_BOOL && a->d.bval);
}

ChpyVal* chpy_is_op(ChpyVal* a, ChpyVal* b) {
    if (a->type == CHPY_NONE && b->type == CHPY_NONE) return chpy_bool(1);
    if (a->type == CHPY_NONE || b->type == CHPY_NONE) return chpy_bool(0);
    return chpy_bool(a == b);
}

/* ---- Subscript ---- */

ChpyVal* chpy_index(ChpyVal* obj, ChpyVal* idx) {
    if (obj->type == CHPY_NONE) chpy_err_none();
    int i = idx->d.ival;
    if (obj->type == CHPY_LIST) {
        if (i < 0 || i >= obj->d.list.len) chpy_err_index();
        return obj->d.list.elems[i];
    }
    if (obj->type == CHPY_STR) {
        int slen = (int)strlen(obj->d.sval);
        if (i < 0 || i >= slen) chpy_err_index();
        char buf[2];
        buf[0] = obj->d.sval[i];
        buf[1] = '\0';
        return chpy_str(buf);
    }
    fprintf(stderr, "Unsupported operation\n");
    exit(6);
}

void chpy_index_set(ChpyVal* obj, ChpyVal* idx, ChpyVal* val) {
    if (obj->type == CHPY_NONE) chpy_err_none();
    if (obj->type == CHPY_LIST) {
        int i = idx->d.ival;
        if (i < 0 || i >= obj->d.list.len) chpy_err_index();
        obj->d.list.elems[i] = val;
        return;
    }
    fprintf(stderr, "Unsupported operation\n");
    exit(6);
}

/* ---- Attributes ---- */

ChpyVal* chpy_get_attr(ChpyVal* obj, int idx) {
    if (obj->type == CHPY_NONE) chpy_err_none();
    if (obj->type != CHPY_OBJ || idx < 0 || idx >= obj->d.obj.nattrs) {
        fprintf(stderr, "Invalid attribute access\n");
        exit(1);
    }
    return obj->d.obj.attrs[idx];
}

void chpy_set_attr(ChpyVal* obj, int idx, ChpyVal* val) {
    if (obj->type == CHPY_NONE) chpy_err_none();
    if (obj->type != CHPY_OBJ || idx < 0 || idx >= obj->d.obj.nattrs) {
        fprintf(stderr, "Invalid attribute access\n");
        exit(1);
    }
    obj->d.obj.attrs[idx] = val;
}

/* ---- Method dispatch ---- */

ChpyVal* chpy_call_method(ChpyVal* obj, int method_idx,
                           int nargs, ChpyVal** args) {
    if (obj->type == CHPY_NONE) chpy_err_none();
    if (obj->type != CHPY_OBJ) {
        fprintf(stderr, "Not an object\n");
        exit(1);
    }
    ChpyFuncPtr method = obj->d.obj.vtable[method_idx];
    int total = nargs + 1;
    ChpyVal** full_args = (ChpyVal**)malloc(sizeof(ChpyVal*) * total);
    full_args[0] = obj;
    for (int i = 0; i < nargs; i++) full_args[i + 1] = args[i];
    ChpyVal* result = method(total, full_args);
    free(full_args);
    return result;
}

/* ---- Iteration ---- */

int chpy_iter_len(ChpyVal* obj) {
    if (obj->type == CHPY_NONE) chpy_err_none();
    if (obj->type == CHPY_LIST) return obj->d.list.len;
    if (obj->type == CHPY_STR) return (int)strlen(obj->d.sval);
    return 0;
}

ChpyVal* chpy_iter_get(ChpyVal* obj, int i) {
    if (obj->type == CHPY_LIST) return obj->d.list.elems[i];
    if (obj->type == CHPY_STR) {
        char buf[2];
        buf[0] = obj->d.sval[i];
        buf[1] = '\0';
        return chpy_str(buf);
    }
    return chpy_none();
}

/* ---- Built-ins ---- */

ChpyVal* chpy_print(ChpyVal* v) {
    switch (v->type) {
    case CHPY_INT:
        printf("%d\n", v->d.ival);
        break;
    case CHPY_BOOL:
        printf("%s\n", v->d.bval ? "True" : "False");
        break;
    case CHPY_STR:
        printf("%s\n", v->d.sval);
        break;
    default:
        fprintf(stderr, "Invalid argument\n");
        exit(1);
    }
    fflush(stdout);
    return chpy_none();
}

ChpyVal* chpy_len(ChpyVal* v) {
    if (v->type == CHPY_STR) return chpy_int((int)strlen(v->d.sval));
    if (v->type == CHPY_LIST) return chpy_int(v->d.list.len);
    fprintf(stderr, "Invalid argument\n");
    exit(1);
}

/* ---- Runtime errors ---- */

void chpy_err_divzero(void) {
    fprintf(stderr, "Division by zero\n");
    exit(2);
}

void chpy_err_index(void) {
    fprintf(stderr, "Index out of bounds\n");
    exit(3);
}

void chpy_err_none(void) {
    fprintf(stderr, "Operation on None\n");
    exit(4);
}

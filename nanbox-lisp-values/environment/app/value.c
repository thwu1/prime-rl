#include "value.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

Value val_nil(void) {
    Value v;
    v.type = VAL_NIL;
    v.as.integer = 0;
    return v;
}

Value val_bool(bool b) {
    Value v;
    v.type = VAL_BOOL;
    v.as.boolean = b;
    return v;
}

Value val_int(int64_t n) {
    Value v;
    v.type = VAL_INT;
    v.as.integer = n;
    return v;
}

Value val_float(double d) {
    Value v;
    v.type = VAL_FLOAT;
    v.as.floating = d;
    return v;
}

Value val_string(char *s) {
    Value v;
    v.type = VAL_STRING;
    v.as.string = s;
    return v;
}

Value val_symbol(char *s) {
    Value v;
    v.type = VAL_SYMBOL;
    v.as.symbol = s;
    return v;
}

Value val_cons(Value car, Value cdr) {
    Cons *c = malloc(sizeof(Cons));
    c->car = car;
    c->cdr = cdr;
    Value v;
    v.type = VAL_CONS;
    v.as.cons = c;
    return v;
}

Value val_builtin(BuiltinFn fn) {
    Value v;
    v.type = VAL_BUILTIN;
    v.as.builtin = fn;
    return v;
}

double val_to_double(Value v) {
    if (v.type == VAL_INT) return (double)v.as.integer;
    if (v.type == VAL_FLOAT) return v.as.floating;
    return 0.0;
}

bool val_truthy(Value v) {
    if (v.type == VAL_NIL) return false;
    if (v.type == VAL_BOOL) return v.as.boolean;
    return true;
}

bool val_equal(Value a, Value b) {
    if (a.type != b.type) {
        if (is_number(a) && is_number(b)) {
            return val_to_double(a) == val_to_double(b);
        }
        return false;
    }
    switch (a.type) {
        case VAL_NIL: return true;
        case VAL_BOOL: return a.as.boolean == b.as.boolean;
        case VAL_INT: return a.as.integer == b.as.integer;
        case VAL_FLOAT: return a.as.floating == b.as.floating;
        case VAL_STRING: return strcmp(a.as.string, b.as.string) == 0;
        case VAL_SYMBOL: return strcmp(a.as.symbol, b.as.symbol) == 0;
        case VAL_CONS: return val_equal(a.as.cons->car, b.as.cons->car) &&
                              val_equal(a.as.cons->cdr, b.as.cons->cdr);
        case VAL_BUILTIN: return a.as.builtin == b.as.builtin;
    }
    return false;
}

const char *val_type_name(Value v) {
    switch (v.type) {
        case VAL_NIL: return "nil";
        case VAL_BOOL: return "boolean";
        case VAL_INT: return "integer";
        case VAL_FLOAT: return "float";
        case VAL_STRING: return "string";
        case VAL_SYMBOL: return "symbol";
        case VAL_CONS: return "cons";
        case VAL_BUILTIN: return "builtin";
    }
    return "unknown";
}

void val_print(Value v, FILE *out) {
    switch (v.type) {
        case VAL_NIL:
            fprintf(out, "nil");
            break;
        case VAL_BOOL:
            fprintf(out, v.as.boolean ? "#t" : "#f");
            break;
        case VAL_INT:
            fprintf(out, "%ld", (long)v.as.integer);
            break;
        case VAL_FLOAT: {
            if (isinf(v.as.floating)) {
                fprintf(out, "%sinf", v.as.floating < 0 ? "-" : "");
            } else if (isnan(v.as.floating)) {
                fprintf(out, "nan");
            } else {
                char buf[32];
                snprintf(buf, sizeof(buf), "%.15g", v.as.floating);
                if (!strchr(buf, '.') && !strchr(buf, 'e') &&
                    !strchr(buf, 'E')) {
                    size_t len = strlen(buf);
                    buf[len] = '.';
                    buf[len + 1] = '0';
                    buf[len + 2] = '\0';
                }
                fprintf(out, "%s", buf);
            }
            break;
        }
        case VAL_STRING:
            fprintf(out, "\"%s\"", v.as.string);
            break;
        case VAL_SYMBOL:
            fprintf(out, "%s", v.as.symbol);
            break;
        case VAL_CONS: {
            fprintf(out, "(");
            Value curr = v;
            bool first = true;
            while (is_cons(curr)) {
                if (!first) fprintf(out, " ");
                first = false;
                val_print(curr.as.cons->car, out);
                curr = curr.as.cons->cdr;
            }
            if (!is_nil(curr)) {
                fprintf(out, " . ");
                val_print(curr, out);
            }
            fprintf(out, ")");
            break;
        }
        case VAL_BUILTIN:
            fprintf(out, "<builtin>");
            break;
    }
}

void val_println(Value v, FILE *out) {
    val_print(v, out);
    fprintf(out, "\n");
}

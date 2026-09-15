#include "value.h"

/* ---- val_cons (needs malloc) ---- */

Value val_cons(Value car, Value cdr) {
    Cons *c = malloc(sizeof(Cons));
    c->car = car;
    c->cdr = cdr;
    return SIGN_BIT | QNAN | PTAG_CONS | ((uint64_t)(uintptr_t)c & PTR_MASK);
}

/* ---- value_type ---- */

ValueType value_type(Value v) {
    if (is_float(v))   return VAL_FLOAT;
    if (is_nil(v))     return VAL_NIL;
    if (is_bool(v))    return VAL_BOOL;
    if (is_int(v))     return VAL_INT;
    if (is_string(v))  return VAL_STRING;
    if (is_symbol(v))  return VAL_SYMBOL;
    if (is_cons(v))    return VAL_CONS;
    if (is_builtin(v)) return VAL_BUILTIN;
    return VAL_NIL;
}

/* ---- val_to_double ---- */

double val_to_double(Value v) {
    if (is_int(v))   return (double)val_get_int(v);
    if (is_float(v)) return val_get_float(v);
    return 0.0;
}

/* ---- val_truthy ---- */

bool val_truthy(Value v) {
    if (is_nil(v))  return false;
    if (is_bool(v)) return val_get_bool(v);
    return true;
}

/* ---- val_equal ---- */

bool val_equal(Value a, Value b) {
    /* numeric cross-type comparison */
    if (is_number(a) && is_number(b))
        return val_to_double(a) == val_to_double(b);

    ValueType ta = value_type(a);
    ValueType tb = value_type(b);
    if (ta != tb) return false;

    switch (ta) {
        case VAL_NIL:     return true;
        case VAL_BOOL:    return a == b;
        case VAL_INT:     return val_get_int(a) == val_get_int(b);
        case VAL_FLOAT:   return val_get_float(a) == val_get_float(b);
        case VAL_STRING:  return strcmp(val_get_string(a), val_get_string(b)) == 0;
        case VAL_SYMBOL:  return strcmp(val_get_symbol(a), val_get_symbol(b)) == 0;
        case VAL_CONS:    return val_equal(val_get_cons(a)->car, val_get_cons(b)->car) &&
                                 val_equal(val_get_cons(a)->cdr, val_get_cons(b)->cdr);
        case VAL_BUILTIN: return a == b;
    }
    return false;
}

/* ---- val_type_name ---- */

const char *val_type_name(Value v) {
    switch (value_type(v)) {
        case VAL_NIL:     return "nil";
        case VAL_BOOL:    return "boolean";
        case VAL_INT:     return "integer";
        case VAL_FLOAT:   return "float";
        case VAL_STRING:  return "string";
        case VAL_SYMBOL:  return "symbol";
        case VAL_CONS:    return "cons";
        case VAL_BUILTIN: return "builtin";
    }
    return "unknown";
}

/* ---- val_print ---- */

void val_print(Value v, FILE *out) {
    switch (value_type(v)) {
        case VAL_NIL:
            fprintf(out, "nil");
            break;
        case VAL_BOOL:
            fprintf(out, val_get_bool(v) ? "#t" : "#f");
            break;
        case VAL_INT:
            fprintf(out, "%ld", (long)val_get_int(v));
            break;
        case VAL_FLOAT: {
            double d = val_get_float(v);
            if (isinf(d)) {
                fprintf(out, "%sinf", d < 0 ? "-" : "");
            } else if (isnan(d)) {
                fprintf(out, "nan");
            } else {
                char buf[32];
                snprintf(buf, sizeof(buf), "%.15g", d);
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
            fprintf(out, "\"%s\"", val_get_string(v));
            break;
        case VAL_SYMBOL:
            fprintf(out, "%s", val_get_symbol(v));
            break;
        case VAL_CONS: {
            fprintf(out, "(");
            Value curr = v;
            bool first = true;
            while (is_cons(curr)) {
                Cons *c = val_get_cons(curr);
                if (!first) fprintf(out, " ");
                first = false;
                val_print(c->car, out);
                curr = c->cdr;
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

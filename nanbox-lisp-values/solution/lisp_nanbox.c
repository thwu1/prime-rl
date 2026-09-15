#include "lisp.h"
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>

/* ------------------------------------------------------------------ */
/*  Environment                                                       */
/* ------------------------------------------------------------------ */

Env *env_bind(Env *env, const char *name, Value value) {
    Env *e = malloc(sizeof(Env));
    e->name = strdup(name);
    e->value = value;
    e->next = env;
    return e;
}

Value env_lookup(Env *env, const char *name, bool *found) {
    for (Env *e = env; e; e = e->next) {
        if (strcmp(e->name, name) == 0) {
            if (found) *found = true;
            return e->value;
        }
    }
    if (found) *found = false;
    return val_nil();
}

/* ------------------------------------------------------------------ */
/*  Reader                                                            */
/* ------------------------------------------------------------------ */

Reader reader_new(const char *input) {
    Reader r;
    r.input = input;
    r.pos = 0;
    r.length = (int)strlen(input);
    return r;
}

static void skip_ws(Reader *r) {
    while (r->pos < r->length) {
        char c = r->input[r->pos];
        if (isspace((unsigned char)c)) {
            r->pos++;
        } else if (c == ';') {
            while (r->pos < r->length && r->input[r->pos] != '\n')
                r->pos++;
        } else {
            break;
        }
    }
}

bool reader_at_end(Reader *r) {
    skip_ws(r);
    return r->pos >= r->length;
}

static bool is_sym_char(char c) {
    return c && !isspace((unsigned char)c) && c != '(' && c != ')' &&
           c != '"' && c != ';' && c != '\'';
}

static Value read_string_lit(Reader *r) {
    r->pos++;
    int start = r->pos;
    while (r->pos < r->length && r->input[r->pos] != '"') {
        if (r->input[r->pos] == '\\') r->pos++;
        r->pos++;
    }
    int raw_len = r->pos - start;
    char *s = malloc(raw_len + 1);
    int j = 0;
    for (int i = start; i < start + raw_len; i++) {
        if (r->input[i] == '\\' && i + 1 < start + raw_len) {
            i++;
            switch (r->input[i]) {
                case 'n':  s[j++] = '\n'; break;
                case 't':  s[j++] = '\t'; break;
                case '\\': s[j++] = '\\'; break;
                case '"':  s[j++] = '"';  break;
                default:   s[j++] = r->input[i]; break;
            }
        } else {
            s[j++] = r->input[i];
        }
    }
    s[j] = '\0';
    if (r->pos < r->length) r->pos++;
    return val_string(s);
}

static Value read_atom(Reader *r) {
    int start = r->pos;
    while (r->pos < r->length && is_sym_char(r->input[r->pos]))
        r->pos++;
    int len = r->pos - start;
    char *tok = malloc(len + 1);
    memcpy(tok, r->input + start, len);
    tok[len] = '\0';

    if (strcmp(tok, "nil") == 0)   { free(tok); return val_nil(); }
    if (strcmp(tok, "#t") == 0)    { free(tok); return val_bool(true); }
    if (strcmp(tok, "#f") == 0)    { free(tok); return val_bool(false); }
    if (strcmp(tok, "true") == 0)  { free(tok); return val_bool(true); }
    if (strcmp(tok, "false") == 0) { free(tok); return val_bool(false); }

    char *end;
    long long n = strtoll(tok, &end, 10);
    if (*end == '\0') { free(tok); return val_int((int64_t)n); }

    double d = strtod(tok, &end);
    if (*end == '\0') { free(tok); return val_float(d); }

    return val_symbol(tok);
}

Value read_expr(Reader *r) {
    skip_ws(r);
    if (r->pos >= r->length) return val_nil();

    char c = r->input[r->pos];

    if (c == '\'') {
        r->pos++;
        Value quoted = read_expr(r);
        return val_cons(val_symbol(strdup("quote")),
                        val_cons(quoted, val_nil()));
    }

    if (c == '(') {
        r->pos++;
        skip_ws(r);
        if (r->pos < r->length && r->input[r->pos] == ')') {
            r->pos++;
            return val_nil();
        }

        Value first = read_expr(r);
        Value list = val_cons(first, val_nil());
        Value tail = list;

        while (1) {
            skip_ws(r);
            if (r->pos >= r->length || r->input[r->pos] == ')') break;

            if (r->input[r->pos] == '.' &&
                (r->pos + 1 >= r->length ||
                 !is_sym_char(r->input[r->pos + 1]))) {
                r->pos++;
                Value rest = read_expr(r);
                val_get_cons(tail)->cdr = rest;
                skip_ws(r);
                break;
            }

            Value next = read_expr(r);
            Value new_tail = val_cons(next, val_nil());
            val_get_cons(tail)->cdr = new_tail;
            tail = new_tail;
        }
        if (r->pos < r->length && r->input[r->pos] == ')') r->pos++;
        return list;
    }

    if (c == '"') return read_string_lit(r);
    return read_atom(r);
}

/* ------------------------------------------------------------------ */
/*  Built-in functions                                                */
/* ------------------------------------------------------------------ */

static Value builtin_add(Value *args, int nargs) {
    double sum = 0;
    bool all_int = true;
    for (int i = 0; i < nargs; i++) {
        if (is_float(args[i])) all_int = false;
        sum += val_to_double(args[i]);
    }
    if (all_int) {
        int64_t isum = 0;
        for (int i = 0; i < nargs; i++) isum += val_get_int(args[i]);
        return val_int(isum);
    }
    return val_float(sum);
}

static Value builtin_sub(Value *args, int nargs) {
    if (nargs == 0) return val_int(0);
    if (nargs == 1) {
        if (is_int(args[0]))
            return val_int(-val_get_int(args[0]));
        return val_float(-val_to_double(args[0]));
    }
    double result = val_to_double(args[0]);
    bool all_int = is_int(args[0]);
    for (int i = 1; i < nargs; i++) {
        if (is_float(args[i])) all_int = false;
        result -= val_to_double(args[i]);
    }
    if (all_int) {
        int64_t r = val_get_int(args[0]);
        for (int i = 1; i < nargs; i++) r -= val_get_int(args[i]);
        return val_int(r);
    }
    return val_float(result);
}

static Value builtin_mul(Value *args, int nargs) {
    double product = 1;
    bool all_int = true;
    for (int i = 0; i < nargs; i++) {
        if (is_float(args[i])) all_int = false;
        product *= val_to_double(args[i]);
    }
    if (all_int) {
        int64_t ip = 1;
        for (int i = 0; i < nargs; i++) ip *= val_get_int(args[i]);
        return val_int(ip);
    }
    return val_float(product);
}

static Value builtin_div(Value *args, int nargs) {
    if (nargs < 2) return val_nil();
    double result = val_to_double(args[0]);
    for (int i = 1; i < nargs; i++)
        result /= val_to_double(args[i]);
    return val_float(result);
}

static Value builtin_modulo(Value *args, int nargs) {
    if (nargs != 2) return val_nil();
    if (is_int(args[0]) && is_int(args[1])) {
        int32_t b = val_get_int(args[1]);
        if (b == 0) return val_nil();
        return val_int(val_get_int(args[0]) % b);
    }
    return val_float(fmod(val_to_double(args[0]), val_to_double(args[1])));
}

static Value builtin_abs(Value *args, int nargs) {
    if (nargs != 1) return val_nil();
    if (is_int(args[0])) {
        int32_t n = val_get_int(args[0]);
        return val_int(n < 0 ? -(int64_t)n : (int64_t)n);
    }
    return val_float(fabs(val_to_double(args[0])));
}

static Value builtin_eq(Value *args, int nargs) {
    if (nargs < 2) return val_bool(true);
    for (int i = 1; i < nargs; i++)
        if (!val_equal(args[0], args[i])) return val_bool(false);
    return val_bool(true);
}

static Value builtin_lt(Value *args, int nargs) {
    if (nargs < 2) return val_bool(true);
    for (int i = 0; i < nargs - 1; i++)
        if (val_to_double(args[i]) >= val_to_double(args[i + 1]))
            return val_bool(false);
    return val_bool(true);
}

static Value builtin_gt(Value *args, int nargs) {
    if (nargs < 2) return val_bool(true);
    for (int i = 0; i < nargs - 1; i++)
        if (val_to_double(args[i]) <= val_to_double(args[i + 1]))
            return val_bool(false);
    return val_bool(true);
}

static Value builtin_le(Value *args, int nargs) {
    if (nargs < 2) return val_bool(true);
    for (int i = 0; i < nargs - 1; i++)
        if (val_to_double(args[i]) > val_to_double(args[i + 1]))
            return val_bool(false);
    return val_bool(true);
}

static Value builtin_ge(Value *args, int nargs) {
    if (nargs < 2) return val_bool(true);
    for (int i = 0; i < nargs - 1; i++)
        if (val_to_double(args[i]) < val_to_double(args[i + 1]))
            return val_bool(false);
    return val_bool(true);
}

static Value builtin_cons(Value *args, int nargs) {
    if (nargs != 2) return val_nil();
    return val_cons(args[0], args[1]);
}

static Value builtin_car(Value *args, int nargs) {
    if (nargs != 1 || !is_cons(args[0])) return val_nil();
    return val_get_cons(args[0])->car;
}

static Value builtin_cdr(Value *args, int nargs) {
    if (nargs != 1 || !is_cons(args[0])) return val_nil();
    return val_get_cons(args[0])->cdr;
}

static Value builtin_list(Value *args, int nargs) {
    Value result = val_nil();
    for (int i = nargs - 1; i >= 0; i--)
        result = val_cons(args[i], result);
    return result;
}

static Value builtin_length(Value *args, int nargs) {
    if (nargs != 1) return val_int(0);
    if (is_string(args[0]))
        return val_int((int64_t)strlen(val_get_string(args[0])));
    int len = 0;
    Value v = args[0];
    while (is_cons(v)) {
        len++;
        v = val_get_cons(v)->cdr;
    }
    return val_int(len);
}

static Value builtin_not(Value *args, int nargs) {
    if (nargs != 1) return val_nil();
    return val_bool(!val_truthy(args[0]));
}

static Value builtin_is_nil(Value *args, int nargs) {
    if (nargs != 1) return val_bool(false);
    return val_bool(is_nil(args[0]));
}

static Value builtin_is_number(Value *args, int nargs) {
    if (nargs != 1) return val_bool(false);
    return val_bool(is_number(args[0]));
}

static Value builtin_is_string(Value *args, int nargs) {
    if (nargs != 1) return val_bool(false);
    return val_bool(is_string(args[0]));
}

static Value builtin_is_bool(Value *args, int nargs) {
    if (nargs != 1) return val_bool(false);
    return val_bool(is_bool(args[0]));
}

static Value builtin_is_list(Value *args, int nargs) {
    if (nargs != 1) return val_bool(false);
    return val_bool(is_cons(args[0]) || is_nil(args[0]));
}

static Value builtin_is_symbol(Value *args, int nargs) {
    if (nargs != 1) return val_bool(false);
    return val_bool(is_symbol(args[0]));
}

static Value builtin_string_append(Value *args, int nargs) {
    size_t total = 0;
    for (int i = 0; i < nargs; i++) {
        if (!is_string(args[i])) return val_nil();
        total += strlen(val_get_string(args[i]));
    }
    char *result = malloc(total + 1);
    result[0] = '\0';
    for (int i = 0; i < nargs; i++)
        strcat(result, val_get_string(args[i]));
    return val_string(result);
}

static Value builtin_number_to_string(Value *args, int nargs) {
    if (nargs != 1 || !is_number(args[0])) return val_nil();
    char buf[64];
    if (is_int(args[0]))
        snprintf(buf, sizeof(buf), "%ld", (long)val_get_int(args[0]));
    else
        snprintf(buf, sizeof(buf), "%.15g", val_get_float(args[0]));
    return val_string(strdup(buf));
}

static Value builtin_display(Value *args, int nargs) {
    for (int i = 0; i < nargs; i++) {
        if (is_string(args[i]))
            printf("%s", val_get_string(args[i]));
        else
            val_print(args[i], stdout);
    }
    return val_nil();
}

static Value builtin_newline(Value *args, int nargs) {
    (void)args; (void)nargs;
    printf("\n");
    return val_nil();
}

static Value builtin_equal(Value *args, int nargs) {
    if (nargs != 2) return val_bool(false);
    return val_bool(val_equal(args[0], args[1]));
}

static Value builtin_type_of(Value *args, int nargs) {
    if (nargs != 1) return val_nil();
    return val_symbol(strdup(val_type_name(args[0])));
}

static Value builtin_sizeof_value(Value *args, int nargs) {
    (void)args; (void)nargs;
    return val_int((int64_t)sizeof(Value));
}

/* ------------------------------------------------------------------ */
/*  Evaluator                                                         */
/* ------------------------------------------------------------------ */

static Value eval_list(Value list, Env *env) {
    if (is_nil(list)) return val_nil();
    Cons *c = val_get_cons(list);
    Value head = eval(c->car, env);
    Value rest = eval_list(c->cdr, env);
    return val_cons(head, rest);
}

Value eval(Value expr, Env *env) {
    switch (value_type(expr)) {
        case VAL_NIL:
        case VAL_BOOL:
        case VAL_INT:
        case VAL_FLOAT:
        case VAL_STRING:
        case VAL_BUILTIN:
            return expr;
        case VAL_SYMBOL: {
            bool found;
            Value v = env_lookup(env, val_get_symbol(expr), &found);
            if (!found) {
                fprintf(stderr, "Error: unbound variable '%s'\n",
                        val_get_symbol(expr));
                return val_nil();
            }
            return v;
        }
        case VAL_CONS:
            break;
    }

    Cons *ec = val_get_cons(expr);
    Value head = ec->car;
    Value rest = ec->cdr;

    /* ---- Special forms ---- */
    if (is_symbol(head)) {
        const char *sym = val_get_symbol(head);

        if (strcmp(sym, "quote") == 0) {
            if (is_cons(rest)) return val_get_cons(rest)->car;
            return val_nil();
        }

        if (strcmp(sym, "if") == 0) {
            if (!is_cons(rest)) return val_nil();
            Cons *rc = val_get_cons(rest);
            Value cond = eval(rc->car, env);
            Value branches = rc->cdr;
            if (val_truthy(cond)) {
                if (is_cons(branches))
                    return eval(val_get_cons(branches)->car, env);
                return val_nil();
            } else {
                if (is_cons(branches)) {
                    Value else_branch = val_get_cons(branches)->cdr;
                    if (is_cons(else_branch))
                        return eval(val_get_cons(else_branch)->car, env);
                }
                return val_nil();
            }
        }

        if (strcmp(sym, "let") == 0) {
            if (!is_cons(rest)) return val_nil();
            Cons *rc = val_get_cons(rest);
            Value bindings = rc->car;
            Value body = rc->cdr;
            Env *let_env = env;
            while (is_cons(bindings)) {
                Cons *bc = val_get_cons(bindings);
                Value binding = bc->car;
                if (is_cons(binding)) {
                    Cons *bi = val_get_cons(binding);
                    if (is_symbol(bi->car)) {
                        const char *bname = val_get_symbol(bi->car);
                        Value bval = val_nil();
                        if (is_cons(bi->cdr))
                            bval = eval(val_get_cons(bi->cdr)->car, env);
                        let_env = env_bind(let_env, bname, bval);
                    }
                }
                bindings = bc->cdr;
            }
            Value result = val_nil();
            while (is_cons(body)) {
                Cons *bdc = val_get_cons(body);
                result = eval(bdc->car, let_env);
                body = bdc->cdr;
            }
            return result;
        }

        if (strcmp(sym, "and") == 0) {
            Value result = val_bool(true);
            Value a = rest;
            while (is_cons(a)) {
                Cons *ac = val_get_cons(a);
                result = eval(ac->car, env);
                if (!val_truthy(result)) return result;
                a = ac->cdr;
            }
            return result;
        }

        if (strcmp(sym, "or") == 0) {
            Value result = val_bool(false);
            Value a = rest;
            while (is_cons(a)) {
                Cons *ac = val_get_cons(a);
                result = eval(ac->car, env);
                if (val_truthy(result)) return result;
                a = ac->cdr;
            }
            return result;
        }

        if (strcmp(sym, "begin") == 0) {
            Value result = val_nil();
            Value a = rest;
            while (is_cons(a)) {
                Cons *ac = val_get_cons(a);
                result = eval(ac->car, env);
                a = ac->cdr;
            }
            return result;
        }

        if (strcmp(sym, "cond") == 0) {
            Value clauses = rest;
            while (is_cons(clauses)) {
                Cons *cc = val_get_cons(clauses);
                Value clause = cc->car;
                if (is_cons(clause)) {
                    Cons *cl = val_get_cons(clause);
                    Value pred = cl->car;
                    bool is_else = is_symbol(pred) &&
                                   strcmp(val_get_symbol(pred), "else") == 0;
                    if (is_else || val_truthy(eval(pred, env))) {
                        Value cbody = cl->cdr;
                        Value result = val_nil();
                        while (is_cons(cbody)) {
                            Cons *cbc = val_get_cons(cbody);
                            result = eval(cbc->car, env);
                            cbody = cbc->cdr;
                        }
                        return result;
                    }
                }
                clauses = cc->cdr;
            }
            return val_nil();
        }
    }

    /* ---- Function call ---- */
    Value func = eval(head, env);
    Value evaled = eval_list(rest, env);

    int nargs = 0;
    Value tmp = evaled;
    while (is_cons(tmp)) { nargs++; tmp = val_get_cons(tmp)->cdr; }

    Value *args = malloc(sizeof(Value) * (nargs > 0 ? nargs : 1));
    tmp = evaled;
    for (int i = 0; i < nargs; i++) {
        Cons *tc = val_get_cons(tmp);
        args[i] = tc->car;
        tmp = tc->cdr;
    }

    Value result = val_nil();
    if (is_builtin(func))
        result = val_get_builtin(func)(args, nargs);
    else
        fprintf(stderr, "Error: not a function\n");

    free(args);
    return result;
}

/* ------------------------------------------------------------------ */
/*  Default environment                                               */
/* ------------------------------------------------------------------ */

Env *default_env(void) {
    Env *env = NULL;
    env = env_bind(env, "+",  val_builtin(builtin_add));
    env = env_bind(env, "-",  val_builtin(builtin_sub));
    env = env_bind(env, "*",  val_builtin(builtin_mul));
    env = env_bind(env, "/",  val_builtin(builtin_div));
    env = env_bind(env, "%",  val_builtin(builtin_modulo));
    env = env_bind(env, "abs", val_builtin(builtin_abs));
    env = env_bind(env, "=",  val_builtin(builtin_eq));
    env = env_bind(env, "<",  val_builtin(builtin_lt));
    env = env_bind(env, ">",  val_builtin(builtin_gt));
    env = env_bind(env, "<=", val_builtin(builtin_le));
    env = env_bind(env, ">=", val_builtin(builtin_ge));
    env = env_bind(env, "cons", val_builtin(builtin_cons));
    env = env_bind(env, "car",  val_builtin(builtin_car));
    env = env_bind(env, "cdr",  val_builtin(builtin_cdr));
    env = env_bind(env, "list", val_builtin(builtin_list));
    env = env_bind(env, "length", val_builtin(builtin_length));
    env = env_bind(env, "not", val_builtin(builtin_not));
    env = env_bind(env, "nil?",     val_builtin(builtin_is_nil));
    env = env_bind(env, "number?",  val_builtin(builtin_is_number));
    env = env_bind(env, "string?",  val_builtin(builtin_is_string));
    env = env_bind(env, "boolean?", val_builtin(builtin_is_bool));
    env = env_bind(env, "list?",    val_builtin(builtin_is_list));
    env = env_bind(env, "symbol?",  val_builtin(builtin_is_symbol));
    env = env_bind(env, "display",  val_builtin(builtin_display));
    env = env_bind(env, "newline",  val_builtin(builtin_newline));
    env = env_bind(env, "string-append",   val_builtin(builtin_string_append));
    env = env_bind(env, "number->string",  val_builtin(builtin_number_to_string));
    env = env_bind(env, "equal?",   val_builtin(builtin_equal));
    env = env_bind(env, "type-of",  val_builtin(builtin_type_of));
    env = env_bind(env, "sizeof-value", val_builtin(builtin_sizeof_value));
    return env;
}

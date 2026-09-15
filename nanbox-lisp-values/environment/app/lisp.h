#ifndef LISP_H
#define LISP_H

#include "value.h"

typedef struct Env {
    char *name;
    Value value;
    struct Env *next;
} Env;

Env *env_bind(Env *env, const char *name, Value value);
Value env_lookup(Env *env, const char *name, bool *found);

typedef struct {
    const char *input;
    int pos;
    int length;
} Reader;

Reader reader_new(const char *input);
Value read_expr(Reader *r);
bool reader_at_end(Reader *r);

Value eval(Value expr, Env *env);
Env *default_env(void);

#endif

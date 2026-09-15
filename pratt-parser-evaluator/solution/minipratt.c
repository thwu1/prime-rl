/* minipratt.c -- MiniPratt Pratt parser and tree-walking evaluator */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "tokens.h"

extern FILE *yyin;

/* ===== AST ===== */

typedef enum {
    N_NUM, N_VAR, N_BINOP, N_UNARY, N_TERNARY,
    N_LET, N_IF, N_CALL, N_FNDEF, N_OPDEF,
    N_CUSTOM_BINOP, N_CUSTOM_UNARY,
} NodeKind;

typedef enum {
    OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MOD, OP_POW,
    OP_EQ, OP_NE, OP_LT, OP_GT, OP_LE, OP_GE,
    OP_SHL, OP_SHR, OP_BAND, OP_BOR, OP_BXOR,
    OP_LAND, OP_LOR, OP_NEG, OP_LNOT, OP_BNOT,
} OpKind;

typedef struct Node Node;
struct Node {
    NodeKind kind;
    union {
        long long num_val;
        char *var_name;
        struct { OpKind op; Node *left, *right; } binop;
        struct { OpKind op; Node *operand; } unary;
        struct { Node *cond, *then_e, *else_e; } ternary;
        struct { char *name; Node *value, *body; } let;
        struct { Node *cond, *then_e, *else_e; } if_expr;
        struct { char *name; Node **args; int nargs; } call;
        struct { char *name; char **params; int nparams; Node *body; } fndef;
        struct { int fixity; int prec; char *name; char **params; int nparams;
                 Node *body; } opdef;
        struct { char *name; Node *left, *right; } cbinop;
        struct { char *name; Node *operand; } cunary;
    } d;
};

static Node *node_new(NodeKind k) {
    Node *n = calloc(1, sizeof(Node));
    n->kind = k;
    return n;
}

static Node *make_num(long long v) {
    Node *n = node_new(N_NUM);
    n->d.num_val = v;
    return n;
}

static Node *make_var(char *name) {
    Node *n = node_new(N_VAR);
    n->d.var_name = name;
    return n;
}

static Node *make_binop(OpKind op, Node *l, Node *r) {
    Node *n = node_new(N_BINOP);
    n->d.binop.op = op;
    n->d.binop.left = l;
    n->d.binop.right = r;
    return n;
}

static Node *make_unary(OpKind op, Node *operand) {
    Node *n = node_new(N_UNARY);
    n->d.unary.op = op;
    n->d.unary.operand = operand;
    return n;
}

static Node *make_ternary(Node *c, Node *t, Node *e) {
    Node *n = node_new(N_TERNARY);
    n->d.ternary.cond = c;
    n->d.ternary.then_e = t;
    n->d.ternary.else_e = e;
    return n;
}

static Node *make_let(char *name, Node *val, Node *body) {
    Node *n = node_new(N_LET);
    n->d.let.name = name;
    n->d.let.value = val;
    n->d.let.body = body;
    return n;
}

static Node *make_if(Node *c, Node *t, Node *e) {
    Node *n = node_new(N_IF);
    n->d.if_expr.cond = c;
    n->d.if_expr.then_e = t;
    n->d.if_expr.else_e = e;
    return n;
}

static Node *make_call(char *name, Node **args, int nargs) {
    Node *n = node_new(N_CALL);
    n->d.call.name = name;
    n->d.call.args = args;
    n->d.call.nargs = nargs;
    return n;
}

static Node *make_fndef(char *name, char **params, int np, Node *body) {
    Node *n = node_new(N_FNDEF);
    n->d.fndef.name = name;
    n->d.fndef.params = params;
    n->d.fndef.nparams = np;
    n->d.fndef.body = body;
    return n;
}

static Node *make_opdef(int fixity, int prec, char *name, char **params,
                         int np, Node *body) {
    Node *n = node_new(N_OPDEF);
    n->d.opdef.fixity = fixity;
    n->d.opdef.prec = prec;
    n->d.opdef.name = name;
    n->d.opdef.params = params;
    n->d.opdef.nparams = np;
    n->d.opdef.body = body;
    return n;
}

static Node *make_cbinop(char *name, Node *l, Node *r) {
    Node *n = node_new(N_CUSTOM_BINOP);
    n->d.cbinop.name = name;
    n->d.cbinop.left = l;
    n->d.cbinop.right = r;
    return n;
}

static Node *make_cunary(char *name, Node *operand) {
    Node *n = node_new(N_CUSTOM_UNARY);
    n->d.cunary.name = name;
    n->d.cunary.operand = operand;
    return n;
}

/* ===== Custom operator registry (for parser) ===== */

typedef struct CustOp CustOp;
struct CustOp {
    char name[256];
    int prec;
    int right_assoc;
    CustOp *next;
};

static CustOp *cinfix_ops = NULL;
static CustOp *cprefix_ops = NULL;

static CustOp *find_cinfix(const char *name) {
    for (CustOp *o = cinfix_ops; o; o = o->next)
        if (strcmp(o->name, name) == 0) return o;
    return NULL;
}

static CustOp *find_cprefix(const char *name) {
    for (CustOp *o = cprefix_ops; o; o = o->next)
        if (strcmp(o->name, name) == 0) return o;
    return NULL;
}

static void reg_cinfix(const char *name, int prec, int ra) {
    CustOp *o = calloc(1, sizeof(CustOp));
    strncpy(o->name, name, 255);
    o->prec = prec;
    o->right_assoc = ra;
    o->next = cinfix_ops;
    cinfix_ops = o;
}

static void reg_cprefix(const char *name, int prec) {
    CustOp *o = calloc(1, sizeof(CustOp));
    strncpy(o->name, name, 255);
    o->prec = prec;
    o->next = cprefix_ops;
    cprefix_ops = o;
}

/* ===== Tokenizer interface ===== */

static int tok;
static TokenValue tok_val;

static void advance(void) {
    tok = yylex();
    tok_val = yylval;
}

static void expect_tok(int t) {
    if (tok != t) {
        fprintf(stderr, "Parse error: expected token %d, got %d\n", t, tok);
        exit(1);
    }
    advance();
}

static char *expect_ident(void) {
    if (tok != TOK_IDENT) {
        fprintf(stderr, "Parse error: expected identifier, got token %d\n", tok);
        exit(1);
    }
    char *s = strdup(tok_val.sval);
    advance();
    return s;
}

/* ===== Parser ===== */

static Node *parse_expr(int min_bp);

static int builtin_infix_info(int t, int *prec, int *ra) {
    *ra = 0;
    switch (t) {
    case TOK_LOR:                          *prec = 3;  return 1;
    case TOK_LAND:                         *prec = 4;  return 1;
    case '|':                              *prec = 5;  return 1;
    case '^':                              *prec = 6;  return 1;
    case '&':                              *prec = 7;  return 1;
    case TOK_EQEQ: case TOK_NE:           *prec = 8;  return 1;
    case '<': case '>':
    case TOK_LE: case TOK_GE:             *prec = 9;  return 1;
    case TOK_SHL: case TOK_SHR:           *prec = 10; return 1;
    case '+': case '-':                    *prec = 11; return 1;
    case '*': case '/': case '%':          *prec = 12; return 1;
    case TOK_STARSTAR: *prec = 14; *ra = 1; return 1;
    default: return 0;
    }
}

static OpKind tok_to_binop(int t) {
    switch (t) {
    case '+': return OP_ADD; case '-': return OP_SUB;
    case '*': return OP_MUL; case '/': return OP_DIV; case '%': return OP_MOD;
    case TOK_STARSTAR: return OP_POW;
    case TOK_EQEQ: return OP_EQ; case TOK_NE: return OP_NE;
    case '<': return OP_LT; case '>': return OP_GT;
    case TOK_LE: return OP_LE; case TOK_GE: return OP_GE;
    case TOK_SHL: return OP_SHL; case TOK_SHR: return OP_SHR;
    case '&': return OP_BAND; case '|': return OP_BOR; case '^': return OP_BXOR;
    case TOK_LAND: return OP_LAND; case TOK_LOR: return OP_LOR;
    default: return (OpKind)-1;
    }
}

static int get_infix_bp(void) {
    int p, r;
    if (builtin_infix_info(tok, &p, &r)) return p;
    if (tok == TOK_IDENT && find_cinfix(tok_val.sval))
        return find_cinfix(tok_val.sval)->prec;
    if (tok == '?') return 2;
    if (tok == '(') return 16;
    return -1;
}

static void parse_params(char ***out, int *nout) {
    int cap = 4, n = 0;
    char **p = malloc(cap * sizeof(char *));
    if (tok == TOK_IDENT) {
        p[n++] = strdup(tok_val.sval);
        advance();
        while (tok == ',') {
            advance();
            if (n >= cap) { cap *= 2; p = realloc(p, cap * sizeof(char *)); }
            if (tok != TOK_IDENT) {
                fprintf(stderr, "Expected parameter name\n");
                exit(1);
            }
            p[n++] = strdup(tok_val.sval);
            advance();
        }
    }
    *out = p;
    *nout = n;
}

static Node *parse_nud(void) {
    /* prefix operators: - ! ~ */
    if (tok == '-' || tok == '!' || tok == '~') {
        int c = tok;
        advance();
        OpKind op = (c == '-') ? OP_NEG : (c == '!') ? OP_LNOT : OP_BNOT;
        return make_unary(op, parse_expr(13));
    }

    /* custom prefix operator */
    if (tok == TOK_IDENT) {
        CustOp *cp = find_cprefix(tok_val.sval);
        if (cp) {
            char *name = strdup(tok_val.sval);
            int prec = cp->prec;
            advance();
            return make_cunary(name, parse_expr(prec));
        }
    }

    /* number literal */
    if (tok == TOK_NUM) {
        long long v = tok_val.ival;
        advance();
        return make_num(v);
    }

    /* identifier (variable) */
    if (tok == TOK_IDENT) {
        char *s = strdup(tok_val.sval);
        advance();
        return make_var(s);
    }

    /* parenthesized expression */
    if (tok == '(') {
        advance();
        Node *e = parse_expr(0);
        expect_tok(')');
        return e;
    }

    /* let ... in ... */
    if (tok == TOK_LET) {
        advance();
        char *name = expect_ident();
        expect_tok('=');
        Node *val = parse_expr(0);
        expect_tok(TOK_IN);
        return make_let(name, val, parse_expr(0));
    }

    /* if ... then ... else ... */
    if (tok == TOK_IF) {
        advance();
        Node *cond = parse_expr(0);
        expect_tok(TOK_THEN);
        Node *then_e = parse_expr(0);
        expect_tok(TOK_ELSE);
        return make_if(cond, then_e, parse_expr(0));
    }

    fprintf(stderr, "Unexpected token %d in expression\n", tok);
    exit(1);
}

static Node *parse_expr(int min_bp) {
    Node *left = parse_nud();

    for (;;) {
        int bp = get_infix_bp();
        if (bp < min_bp) break;

        /* ternary: ? ... : ... */
        if (tok == '?') {
            advance();
            Node *mid = parse_expr(0);
            expect_tok(':');
            left = make_ternary(left, mid, parse_expr(2));
            continue;
        }

        /* function call: name(args) */
        if (tok == '(' && left->kind == N_VAR) {
            advance();
            int cap = 4, na = 0;
            Node **args = malloc(cap * sizeof(Node *));
            if (tok != ')') {
                args[na++] = parse_expr(0);
                while (tok == ',') {
                    advance();
                    if (na >= cap) {
                        cap *= 2;
                        args = realloc(args, cap * sizeof(Node *));
                    }
                    args[na++] = parse_expr(0);
                }
            }
            expect_tok(')');
            left = make_call(left->d.var_name, args, na);
            continue;
        }

        /* custom infix operator */
        if (tok == TOK_IDENT) {
            CustOp *ci = find_cinfix(tok_val.sval);
            if (ci) {
                char *name = strdup(tok_val.sval);
                int prec = ci->prec;
                int ra = ci->right_assoc;
                advance();
                int nbp = ra ? prec : prec + 1;
                left = make_cbinop(name, left, parse_expr(nbp));
                continue;
            }
        }

        /* built-in infix operator */
        {
            int prec, ra;
            if (builtin_infix_info(tok, &prec, &ra)) {
                OpKind op = tok_to_binop(tok);
                advance();
                int nbp = ra ? prec : prec + 1;
                left = make_binop(op, left, parse_expr(nbp));
                continue;
            }
        }

        break;
    }

    return left;
}

/* ===== Top-level program ===== */

typedef struct TopItem TopItem;
struct TopItem { Node *node; TopItem *next; };

static TopItem *parse_program(void) {
    TopItem *head = NULL, **tail = &head;

    while (tok != TOK_EOF) {
        Node *item;

        if (tok == TOK_FN) {
            advance();
            char *name = expect_ident();
            expect_tok('(');
            char **params; int np;
            parse_params(&params, &np);
            expect_tok(')');
            expect_tok('=');
            item = make_fndef(name, params, np, parse_expr(0));
        } else if (tok == TOK_OPERATOR) {
            advance();
            int fixity;
            if (tok == TOK_INFIXL) fixity = 0;
            else if (tok == TOK_INFIXR) fixity = 1;
            else if (tok == TOK_PREFIX) fixity = 2;
            else {
                fprintf(stderr, "Expected fixity keyword\n");
                exit(1);
            }
            advance();

            if (tok != TOK_NUM) {
                fprintf(stderr, "Expected precedence number\n");
                exit(1);
            }
            int prec = (int)tok_val.ival;
            advance();

            char *name = expect_ident();
            expect_tok('(');
            char **params; int np;
            parse_params(&params, &np);
            expect_tok(')');
            expect_tok('=');
            Node *body = parse_expr(0);

            /* Register custom operator for subsequent parsing */
            if (fixity <= 1) reg_cinfix(name, prec, fixity);
            else reg_cprefix(name, prec);

            item = make_opdef(fixity, prec, name, params, np, body);
        } else {
            item = parse_expr(0);
        }

        /* consume optional semicolons */
        while (tok == ';') advance();

        TopItem *ti = calloc(1, sizeof(TopItem));
        ti->node = item;
        *tail = ti;
        tail = &ti->next;
    }

    return head;
}

/* ===== Evaluator ===== */

typedef struct Env Env;
struct Env {
    char *name;
    long long value;
    Env *next;
};

typedef struct FnEntry FnEntry;
struct FnEntry {
    char *name;
    char **params;
    int nparams;
    Node *body;
    FnEntry *next;
};

static FnEntry *fn_table = NULL;
static FnEntry *op_eval_table = NULL;
static Env *global_env = NULL;

static void add_fn(const char *name, char **params, int np, Node *body) {
    FnEntry *f = calloc(1, sizeof(FnEntry));
    f->name = strdup(name);
    f->params = params;
    f->nparams = np;
    f->body = body;
    f->next = fn_table;
    fn_table = f;
}

static FnEntry *get_fn(const char *name) {
    for (FnEntry *f = fn_table; f; f = f->next)
        if (strcmp(f->name, name) == 0) return f;
    return NULL;
}

static void add_op_eval(const char *name, char **params, int np, Node *body) {
    FnEntry *f = calloc(1, sizeof(FnEntry));
    f->name = strdup(name);
    f->params = params;
    f->nparams = np;
    f->body = body;
    f->next = op_eval_table;
    op_eval_table = f;
}

static FnEntry *get_op_eval(const char *name) {
    for (FnEntry *f = op_eval_table; f; f = f->next)
        if (strcmp(f->name, name) == 0) return f;
    return NULL;
}

static Env *env_push(Env *parent, const char *name, long long val) {
    Env *e = calloc(1, sizeof(Env));
    e->name = strdup(name);
    e->value = val;
    e->next = parent;
    return e;
}

static long long env_get(Env *env, const char *name) {
    for (Env *e = env; e; e = e->next)
        if (strcmp(e->name, name) == 0) return e->value;
    fprintf(stderr, "Undefined variable: %s\n", name);
    exit(1);
}

static long long ipow(long long base, long long exp) {
    long long result = 1;
    while (exp > 0) {
        if (exp & 1) result *= base;
        base *= base;
        exp >>= 1;
    }
    return result;
}

static long long eval_node(Node *n, Env *env) {
    switch (n->kind) {
    case N_NUM:
        return n->d.num_val;

    case N_VAR:
        return env_get(env, n->d.var_name);

    case N_BINOP: {
        OpKind op = n->d.binop.op;

        /* short-circuit logical operators */
        if (op == OP_LAND) {
            long long l = eval_node(n->d.binop.left, env);
            if (l == 0) return 0;
            return eval_node(n->d.binop.right, env) != 0 ? 1 : 0;
        }
        if (op == OP_LOR) {
            long long l = eval_node(n->d.binop.left, env);
            if (l != 0) return 1;
            return eval_node(n->d.binop.right, env) != 0 ? 1 : 0;
        }

        long long l = eval_node(n->d.binop.left, env);
        long long r = eval_node(n->d.binop.right, env);

        switch (op) {
        case OP_ADD: return l + r;
        case OP_SUB: return l - r;
        case OP_MUL: return l * r;
        case OP_DIV:
            if (r == 0) { fprintf(stderr, "Division by zero\n"); exit(1); }
            return l / r;
        case OP_MOD:
            if (r == 0) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
            return l - (l / r) * r;
        case OP_POW: return ipow(l, r);
        case OP_EQ:  return l == r ? 1 : 0;
        case OP_NE:  return l != r ? 1 : 0;
        case OP_LT:  return l <  r ? 1 : 0;
        case OP_GT:  return l >  r ? 1 : 0;
        case OP_LE:  return l <= r ? 1 : 0;
        case OP_GE:  return l >= r ? 1 : 0;
        case OP_SHL: return l << r;
        case OP_SHR: return l >> r;
        case OP_BAND: return l & r;
        case OP_BOR:  return l | r;
        case OP_BXOR: return l ^ r;
        default: break;
        }
        break;
    }

    case N_UNARY: {
        long long v = eval_node(n->d.unary.operand, env);
        switch (n->d.unary.op) {
        case OP_NEG:  return -v;
        case OP_LNOT: return v == 0 ? 1 : 0;
        case OP_BNOT: return ~v;
        default: break;
        }
        break;
    }

    case N_TERNARY: {
        long long c = eval_node(n->d.ternary.cond, env);
        return eval_node(c ? n->d.ternary.then_e : n->d.ternary.else_e, env);
    }

    case N_LET: {
        long long v = eval_node(n->d.let.value, env);
        return eval_node(n->d.let.body, env_push(env, n->d.let.name, v));
    }

    case N_IF: {
        long long c = eval_node(n->d.if_expr.cond, env);
        return eval_node(c ? n->d.if_expr.then_e : n->d.if_expr.else_e, env);
    }

    case N_CALL: {
        FnEntry *fn = get_fn(n->d.call.name);
        if (!fn) {
            fprintf(stderr, "Undefined function: %s\n", n->d.call.name);
            exit(1);
        }
        if (fn->nparams != n->d.call.nargs) {
            fprintf(stderr, "Function %s expects %d args, got %d\n",
                    n->d.call.name, fn->nparams, n->d.call.nargs);
            exit(1);
        }
        Env *fn_env = global_env;
        for (int i = 0; i < fn->nparams; i++) {
            fn_env = env_push(fn_env, fn->params[i],
                              eval_node(n->d.call.args[i], env));
        }
        return eval_node(fn->body, fn_env);
    }

    case N_CUSTOM_BINOP: {
        FnEntry *op = get_op_eval(n->d.cbinop.name);
        if (!op) {
            fprintf(stderr, "Undefined operator: %s\n", n->d.cbinop.name);
            exit(1);
        }
        long long lv = eval_node(n->d.cbinop.left, env);
        long long rv = eval_node(n->d.cbinop.right, env);
        Env *op_env = global_env;
        op_env = env_push(op_env, op->params[0], lv);
        op_env = env_push(op_env, op->params[1], rv);
        return eval_node(op->body, op_env);
    }

    case N_CUSTOM_UNARY: {
        FnEntry *op = get_op_eval(n->d.cunary.name);
        if (!op) {
            fprintf(stderr, "Undefined operator: %s\n", n->d.cunary.name);
            exit(1);
        }
        long long v = eval_node(n->d.cunary.operand, env);
        return eval_node(op->body, env_push(global_env, op->params[0], v));
    }

    case N_FNDEF:
    case N_OPDEF:
        return 0;

    default:
        break;
    }

    fprintf(stderr, "Evaluation error\n");
    exit(1);
}

/* ===== Main ===== */

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <file.mp>\n", argv[0]);
        return 1;
    }

    yyin = fopen(argv[1], "r");
    if (!yyin) {
        fprintf(stderr, "Cannot open %s\n", argv[1]);
        return 1;
    }

    advance(); /* prime the first token */
    TopItem *prog = parse_program();
    fclose(yyin);

    /* First pass: register all function and operator definitions */
    for (TopItem *it = prog; it; it = it->next) {
        if (it->node->kind == N_FNDEF)
            add_fn(it->node->d.fndef.name, it->node->d.fndef.params,
                   it->node->d.fndef.nparams, it->node->d.fndef.body);
        else if (it->node->kind == N_OPDEF)
            add_op_eval(it->node->d.opdef.name, it->node->d.opdef.params,
                        it->node->d.opdef.nparams, it->node->d.opdef.body);
    }

    /* Second pass: evaluate all expressions, keep last result */
    long long result = 0;
    for (TopItem *it = prog; it; it = it->next) {
        if (it->node->kind != N_FNDEF && it->node->kind != N_OPDEF)
            result = eval_node(it->node, global_env);
    }

    printf("%lld\n", result);
    return 0;
}

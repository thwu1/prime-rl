#define _POSIX_C_SOURCE 200809L
/* regex_engine.c  —  Broken POSIX ERE engine (starter implementation)
 *
 *
 * Architecture: parse ERE → AST → compile to bytecode → backtracking VM.
 */

#include "regex_engine.h"
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* ------------------------------------------------------------------ */
/*  AST                                                                */
/* ------------------------------------------------------------------ */
enum { N_LIT=1, N_DOT, N_CLASS, N_CAT, N_ALT,
       N_STAR, N_PLUS, N_QUEST, N_GROUP, N_BOL, N_EOL };

typedef struct Node {
    int   type;
    int   ch;
    unsigned char cset[32];
    int   neg;
    int   gid;
    struct Node *a, *b;
    struct Node *alloc_next;
} Node;

/* ------------------------------------------------------------------ */
/*  Bytecode instructions                                              */
/* ------------------------------------------------------------------ */
enum { I_CHAR=1, I_ANY, I_CLASS, I_SPLIT, I_JMP, I_SAVE,
       I_BOL, I_EOL, I_MATCH };

typedef struct {
    int   op;
    int   c;
    int   x, y;
    unsigned char cset[32];
    int   neg;
} Inst;

#define MAX_INST 4096
#define MAX_GROUPS 32

/* ------------------------------------------------------------------ */
/*  Internal compiled form                                             */
/* ------------------------------------------------------------------ */
typedef struct {
    Inst  prog[MAX_INST];
    int   len;
    int   ngroups;
    int   cflags;
    char *pat_dup;  /* stored pattern for diagnostics */
} CompiledRE;

/* ------------------------------------------------------------------ */
/*  Parser state                                                       */
/* ------------------------------------------------------------------ */
typedef struct {
    const char *pat;
    int   pos, plen;
    int   ngroups;
    int   err;
    Node *alloc_head;
} PCtx;

static Node *pnew(PCtx *c, int type) {
    Node *n = calloc(1, sizeof *n);
    if (!n) { c->err = REG_ESPACE; return NULL; }
    n->type = type;
    n->alloc_next = c->alloc_head;
    c->alloc_head = n;
    return n;
}
static void pfree_all(PCtx *c) {
    Node *n = c->alloc_head;
    while (n) { Node *t = n->alloc_next; free(n); n = t; }
    c->alloc_head = NULL;
}

static int pk(PCtx *c) { return c->pos < c->plen ? (unsigned char)c->pat[c->pos] : -1; }
static int nx(PCtx *c) { return c->pos < c->plen ? (unsigned char)c->pat[c->pos++] : -1; }

/* Forward declarations */
static Node *p_alt(PCtx *c);
static Node *p_cat(PCtx *c);
static Node *p_rep(PCtx *c);
static Node *p_atom(PCtx *c);
static Node *p_bracket(PCtx *c);

static void cset_add(unsigned char *s, int ch) { s[ch/8] |= 1u << (ch%8); }
static int  cset_has(const unsigned char *s, int ch) { return (s[ch/8]>>(ch%8))&1; }

/* ---- alternation ---- */
static Node *p_alt(PCtx *c) {
    Node *left = p_cat(c);
    if (!left || c->err) return NULL;
    while (pk(c) == '|') {
        nx(c);
        Node *right = p_cat(c);
        if (!right) return NULL;
        Node *n = pnew(c, N_ALT);
        if (!n) return NULL;
        n->a = left; n->b = right;
        left = n;
    }
    return left;
}

/* ---- concatenation ---- */
static Node *p_cat(PCtx *c) {
    Node *left = p_rep(c);
    if (!left || c->err) return NULL;
    while (pk(c) != -1 && pk(c) != '|' && pk(c) != ')') {
        Node *right = p_rep(c);
        if (!right) return NULL;
        Node *n = pnew(c, N_CAT);
        if (!n) return NULL;
        n->a = left; n->b = right;
        left = n;
    }
    return left;
}

/* ---- repetition ---- */
static Node *p_rep(PCtx *c) {
    Node *atom = p_atom(c);
    if (!atom || c->err) return NULL;
    int ch = pk(c);
    if (ch == '*' || ch == '+' || ch == '?') {
        nx(c);
        /* BUG: does not detect multiple adjacent quantifiers */
        /* BUG: does not handle {m,n} interval expressions   */
        int t = (ch == '*') ? N_STAR : (ch == '+') ? N_PLUS : N_QUEST;
        Node *n = pnew(c, t);
        if (!n) return NULL;
        n->a = atom;
        return n;
    }
    /* BUG: '{' is treated as a literal – interval expressions not supported */
    return atom;
}

/* ---- atom ---- */
static Node *p_atom(PCtx *c) {
    int ch = pk(c);
    if (ch == -1) return NULL;

    if (ch == '(') {
        nx(c);
        c->ngroups++;
        int gid = c->ngroups;
        Node *inner = p_alt(c);
        if (pk(c) != ')') {
            c->err = REG_BADPAT;   /* BUG: should be REG_EPAREN */
            return NULL;
        }
        nx(c);
        Node *n = pnew(c, N_GROUP);
        if (!n) return NULL;
        n->gid = gid;
        n->a = inner;
        return n;
    }
    if (ch == ')') return NULL;   /* unmatched ) – let caller handle */

    if (ch == '[') return p_bracket(c);

    if (ch == '.') { nx(c); return pnew(c, N_DOT); }
    if (ch == '^') { nx(c); return pnew(c, N_BOL); }
    if (ch == '$') { nx(c); return pnew(c, N_EOL); }

    if (ch == '\\') {
        nx(c);
        ch = pk(c);
        if (ch == -1) {
            c->err = REG_BADPAT;   /* BUG: should be REG_EESCAPE */
            return NULL;
        }
        nx(c);
        Node *n = pnew(c, N_LIT);
        if (!n) return NULL;
        n->ch = ch;
        return n;
    }

    /* ordinary char */
    nx(c);
    Node *n = pnew(c, N_LIT);
    if (!n) return NULL;
    n->ch = ch;
    return n;
}

/* ---- bracket expression ---- */
static Node *p_bracket(PCtx *c) {
    nx(c); /* consume '[' */
    Node *n = pnew(c, N_CLASS);
    if (!n) return NULL;
    int negate = 0;
    if (pk(c) == '^') { negate = 1; nx(c); }
    n->neg = negate;

    int first = 1;
    while (1) {
        int ch = pk(c);
        if (ch == -1) { c->err = REG_BADPAT; return NULL; } /* BUG: should be REG_EBRACK */
        if (ch == ']' && !first) break;

        /* BUG: does not handle [:class:] character classes */
        /* BUG: does not handle [.sym.] collating symbols   */
        /* BUG: does not handle [=eq=] equivalence classes  */

        nx(c);
        first = 0;

        /* range check */
        if (pk(c) == '-' && c->pos + 1 < c->plen &&
            c->pat[c->pos + 1] != ']')
        {
            nx(c); /* consume '-' */
            int end = nx(c);
            if (end == -1) { c->err = REG_BADPAT; return NULL; }
            if (ch > end) { c->err = REG_BADPAT; return NULL; } /* BUG: should be REG_ERANGE */
            for (int i = ch; i <= end; i++) cset_add(n->cset, i);
        } else {
            cset_add(n->cset, ch);
        }
    }
    nx(c); /* consume ']' */
    return n;
}

/* ------------------------------------------------------------------ */
/*  Compiler: AST → bytecode                                           */
/* ------------------------------------------------------------------ */
static int emit(Inst *prog, int pc, int op) {
    if (pc >= MAX_INST) return pc;
    memset(&prog[pc], 0, sizeof(Inst));
    prog[pc].op = op;
    return pc + 1;
}

static int comp(Node *n, Inst *prog, int pc) {
    if (!n) return pc;
    switch (n->type) {
    case N_LIT:
        prog[pc].op = I_CHAR; prog[pc].c = n->ch;
        return pc + 1;
    case N_DOT:
        return emit(prog, pc, I_ANY);
    case N_CLASS:
        prog[pc].op = I_CLASS;
        memcpy(prog[pc].cset, n->cset, 32);
        prog[pc].neg = n->neg;
        return pc + 1;
    case N_CAT:
        pc = comp(n->a, prog, pc);
        return comp(n->b, prog, pc);
    case N_ALT: {
        int spc = pc++;               /* SPLIT placeholder */
        int l1 = pc;
        pc = comp(n->a, prog, pc);
        int jpc = pc++;               /* JMP placeholder */
        int l2 = pc;
        pc = comp(n->b, prog, pc);
        int l3 = pc;
        prog[spc].op = I_SPLIT; prog[spc].x = l1; prog[spc].y = l2;
        prog[jpc].op = I_JMP;  prog[jpc].x = l3;
        return pc;
    }
    case N_STAR: {
        int l0 = pc;
        prog[pc].op = I_SPLIT; pc++;
        int l1 = pc;
        pc = comp(n->a, prog, pc);
        prog[pc].op = I_JMP; prog[pc].x = l0; pc++;
        int l2 = pc;
        prog[l0].x = l1; prog[l0].y = l2;
        return pc;
    }
    case N_PLUS: {
        int l1 = pc;
        pc = comp(n->a, prog, pc);
        prog[pc].op = I_SPLIT; prog[pc].x = l1; pc++;
        int l2 = pc;
        prog[pc-1].y = l2;
        return pc;
    }
    case N_QUEST: {
        int spc = pc++;
        int l1 = pc;
        pc = comp(n->a, prog, pc);
        int l2 = pc;
        prog[spc].op = I_SPLIT; prog[spc].x = l1; prog[spc].y = l2;
        return pc;
    }
    case N_GROUP:
        prog[pc].op = I_SAVE; prog[pc].x = 2 * n->gid; pc++;
        pc = comp(n->a, prog, pc);
        prog[pc].op = I_SAVE; prog[pc].x = 2 * n->gid + 1; pc++;
        return pc;
    case N_BOL:
        return emit(prog, pc, I_BOL);
    case N_EOL:
        return emit(prog, pc, I_EOL);
    }
    return pc;
}

/* ------------------------------------------------------------------ */
/*  VM: backtracking interpreter                                       */
/* ------------------------------------------------------------------ */
static int vm_run(const Inst *prog, int pc, const char *s, int sp, int len,
                  int cflags, int eflags, int *visited)
{
    for (;;) {
        const Inst *i = &prog[pc];
        switch (i->op) {
        case I_CHAR:
            /* BUG: REG_ICASE not handled */
            if (sp >= len || (unsigned char)s[sp] != i->c) return -1;
            sp++; pc++;
            break;
        case I_ANY:
            /* BUG: REG_NEWLINE not handled – dot should not match \n */
            if (sp >= len) return -1;
            sp++; pc++;
            break;
        case I_CLASS:
            if (sp >= len) return -1;
            { int ch = (unsigned char)s[sp];
              int in = cset_has(i->cset, ch);
              if (i->neg) in = !in;
              if (!in) return -1;
            }
            sp++; pc++;
            break;
        case I_SPLIT: {
            /* cycle detection: prevent infinite loop on zero-width body */
            if (visited[pc] == sp) { pc = i->y; break; }
            int old_v = visited[pc];
            visited[pc] = sp;
            int r = vm_run(prog, i->x, s, sp, len, cflags, eflags, visited);
            visited[pc] = old_v;
            if (r >= 0) return r;   /* BUG: returns first match, not longest (for alternation) */
            pc = i->y;
            break;
        }
        case I_JMP:
            pc = i->x;
            break;
        case I_SAVE:
            /* BUG: subexpression positions are not captured at all */
            pc++;
            break;
        case I_BOL:
            /* BUG: REG_NEWLINE not handled – ^ should also match after \n */
            if (sp != 0) return -1;
            if (eflags & REG_NOTBOL) return -1;
            pc++;
            break;
        case I_EOL:
            /* BUG: REG_NEWLINE not handled – $ should also match before \n */
            if (sp != len) return -1;
            if (eflags & REG_NOTEOL) return -1;
            pc++;
            break;
        case I_MATCH:
            return sp;
        default:
            return -1;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Public API                                                         */
/* ------------------------------------------------------------------ */
int regcomp(regex_t *preg, const char *pattern, int cflags) {
    if (!(cflags & REG_EXTENDED))
        return REG_BADPAT;   /* only ERE supported */

    PCtx ctx;
    memset(&ctx, 0, sizeof ctx);
    ctx.pat  = pattern;
    ctx.plen = (int)strlen(pattern);

    Node *ast = p_alt(&ctx);

    if (ctx.err) { pfree_all(&ctx); return ctx.err; }
    if (ctx.pos != ctx.plen) { pfree_all(&ctx); return REG_BADPAT; }

    CompiledRE *cre = calloc(1, sizeof *cre);
    if (!cre) { pfree_all(&ctx); return REG_ESPACE; }
    cre->pat_dup = strdup(pattern);

    /* Wrap entire expression in group 0 */
    int pc = 0;
    cre->prog[pc].op = I_SAVE; cre->prog[pc].x = 0; pc++;
    pc = comp(ast, cre->prog, pc);
    cre->prog[pc].op = I_SAVE; cre->prog[pc].x = 1; pc++;
    cre->prog[pc].op = I_MATCH; pc++;
    cre->len     = pc;
    cre->ngroups = ctx.ngroups;
    cre->cflags  = cflags;

    pfree_all(&ctx);

    preg->re_nsub = (size_t)cre->ngroups;
    preg->__priv  = cre;
    return 0;
}

int regexec(const regex_t *preg, const char *string,
            size_t nmatch, regmatch_t pmatch[], int eflags)
{
    const CompiledRE *cre = (const CompiledRE *)preg->__priv;
    int len = (int)strlen(string);

    for (int i = 0; i <= len; i++) {
        int visited[MAX_INST];
        memset(visited, -1, sizeof visited);
        int end = vm_run(cre->prog, 0, string, i, len, cre->cflags, eflags, visited);
        if (end >= 0) {
            if (pmatch && nmatch > 0 && !(cre->cflags & REG_NOSUB)) {
                pmatch[0].rm_so = i;
                pmatch[0].rm_eo = end;
                /* BUG: subexpression offsets not populated */
                for (size_t j = 1; j < nmatch; j++) {
                    pmatch[j].rm_so = -1;
                    pmatch[j].rm_eo = -1;
                }
            }
            return 0;
        }
    }
    return REG_NOMATCH;
}

void regfree(regex_t *preg) {
    free(preg->__priv);
    preg->__priv = NULL;
    preg->re_nsub = 0;
}

size_t regerror(int errcode, const regex_t *preg, char *errbuf, size_t errbuf_size) {
    (void)preg;
    static const char *msgs[] = {
        [0]            = "Success",
        [REG_NOMATCH]  = "No match",
        [REG_BADPAT]   = "Invalid regular expression",
        [REG_ECOLLATE] = "Invalid collating element",
        [REG_ECTYPE]   = "Invalid character class",
        [REG_EESCAPE]  = "Trailing backslash",
        [REG_ESUBREG]  = "Invalid back reference",
        [REG_EBRACK]   = "Unmatched [",
        [REG_EPAREN]   = "Unmatched (",
        [REG_EBRACE]   = "Unmatched {",
        [REG_BADBR]    = "Invalid content of {}",
        [REG_ERANGE]   = "Invalid range end",
        [REG_ESPACE]   = "Out of memory",
        [REG_BADRPT]   = "Invalid preceding regular expression",
    };
    const char *msg = (errcode >= 0 && errcode <= REG_BADRPT) ? msgs[errcode] : "Unknown error";
    size_t need = strlen(msg) + 1;
    if (errbuf && errbuf_size > 0) {
        size_t cp = (need < errbuf_size) ? need : errbuf_size;
        memcpy(errbuf, msg, cp - 1);
        errbuf[cp - 1] = '\0';
    }
    return need;
}

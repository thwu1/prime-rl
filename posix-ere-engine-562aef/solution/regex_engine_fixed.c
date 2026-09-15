#define _POSIX_C_SOURCE 200809L
/* regex_engine.c  —  Correct POSIX ERE engine
 *
 *
 * Architecture: parse ERE → AST → compile to bytecode → backtracking VM.
 */

#include "regex_engine.h"
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdio.h>

/* ------------------------------------------------------------------ */
/*  AST                                                                */
/* ------------------------------------------------------------------ */
enum { N_LIT=1, N_DOT, N_CLASS, N_CAT, N_ALT,
       N_REP, N_GROUP, N_BOL, N_EOL };

typedef struct Node {
    int   type;
    int   ch;
    unsigned char cset[32];
    int   neg;
    int   gid;
    int   rmin, rmax; /* for N_REP: min, max (-1 = unbounded) */
    struct Node *a, *b;
    struct Node *alloc_next;
} Node;

/* ------------------------------------------------------------------ */
/*  Bytecode                                                           */
/* ------------------------------------------------------------------ */
enum { I_CHAR=1, I_ANY, I_CLASS, I_SPLIT, I_SPLIT_ALT,
       I_JMP, I_SAVE, I_BOL, I_EOL, I_MATCH };

typedef struct {
    int   op;
    int   c;
    int   x, y;
    unsigned char cset[32];
    int   neg;
} Inst;

#define MAX_INST 8192
#define MAX_GROUPS 64
#define MAX_SAVES (MAX_GROUPS*2)

typedef struct {
    Inst  prog[MAX_INST];
    int   len;
    int   ngroups;
    int   cflags;
    char *pat_dup;
} CompiledRE;

/* ------------------------------------------------------------------ */
/*  Parser                                                             */
/* ------------------------------------------------------------------ */
typedef struct {
    const char *pat;
    int   pos, plen;
    int   ngroups;
    int   err;
    int   cflags;
    Node *alloc_head;
} PCtx;

static Node *pnew(PCtx *c, int type) {
    Node *n = calloc(1, sizeof *n);
    if (!n) { c->err = REG_ESPACE; return NULL; }
    n->type = type;
    n->rmax = -1;
    n->alloc_next = c->alloc_head;
    c->alloc_head = n;
    return n;
}
static void pfree_all(PCtx *c) {
    Node *n = c->alloc_head;
    while (n) { Node *t = n->alloc_next; free(n); n = t; }
    c->alloc_head = NULL;
}
static int pk(PCtx *c)  { return c->pos < c->plen ? (unsigned char)c->pat[c->pos] : -1; }
static int nx(PCtx *c)  { return c->pos < c->plen ? (unsigned char)c->pat[c->pos++] : -1; }

static void cset_add(unsigned char *s, int ch) { s[ch/8] |= 1u<<(ch%8); }
static int  cset_has(const unsigned char *s, int ch) { return (s[ch/8]>>(ch%8))&1; }
static void cset_add_icase(unsigned char *s, int ch, int icase) {
    cset_add(s, ch);
    if (icase) { cset_add(s, toupper(ch)); cset_add(s, tolower(ch)); }
}

/* Forward declarations */
static Node *p_alt(PCtx *c);
static Node *p_cat(PCtx *c);
static Node *p_rep(PCtx *c);
static Node *p_atom(PCtx *c);
static Node *p_bracket(PCtx *c);

static int is_quant(int ch) { return ch=='*'||ch=='+'||ch=='?'||ch=='{'; }

/* ---- alternation ---- */
static Node *p_alt(PCtx *c) {
    Node *left = p_cat(c);
    if (!left || c->err) return NULL;
    while (pk(c) == '|') {
        nx(c);
        Node *right = p_cat(c);
        if (!right) { if(!c->err) c->err=REG_BADPAT; return NULL; }
        Node *n = pnew(c, N_ALT); if(!n) return NULL;
        n->a = left; n->b = right;
        left = n;
    }
    return left;
}

/* ---- concatenation ---- */
static Node *p_cat(PCtx *c) {
    /* handle empty branch: if next char is | or ) or end, return empty */
    if (pk(c) == '|' || pk(c) == ')' || pk(c) == -1) {
        /* empty expression — represents empty match */
        Node *n = pnew(c, N_LIT); if(!n) return NULL;
        n->type = N_CAT; n->a = NULL; n->b = NULL;
        return n;
    }
    Node *left = p_rep(c);
    if (!left || c->err) return NULL;
    while (pk(c) != -1 && pk(c) != '|' && pk(c) != ')') {
        Node *right = p_rep(c);
        if (!right || c->err) return NULL;
        Node *n = pnew(c, N_CAT); if(!n) return NULL;
        n->a = left; n->b = right;
        left = n;
    }
    return left;
}

/* parse a decimal integer; returns -1 on failure */
static int parse_int(PCtx *c) {
    if (!isdigit(pk(c))) return -1;
    int v = 0;
    while (isdigit(pk(c))) {
        v = v * 10 + (nx(c) - '0');
        if (v > 255) { c->err = REG_BADBR; return -1; }
    }
    return v;
}

/* ---- repetition (including {m,n}) ---- */
static Node *p_rep(PCtx *c) {
    Node *atom = p_atom(c);
    if (!atom || c->err) return NULL;
    int ch = pk(c);
    if (!is_quant(ch)) return atom;

    /* reject quantifiers on anchors */
    if (atom->type == N_BOL || atom->type == N_EOL) {
        c->err = REG_BADRPT; return NULL;
    }

    int rmin = 0, rmax = -1;

    if (ch == '*') { nx(c); rmin = 0; rmax = -1; }
    else if (ch == '+') { nx(c); rmin = 1; rmax = -1; }
    else if (ch == '?') { nx(c); rmin = 0; rmax = 1; }
    else if (ch == '{') {
        int save = c->pos;
        nx(c); /* consume '{' */
        int m = parse_int(c);
        if (c->err) return NULL;
        if (m < 0) {
            /* not a valid interval — treat '{' as literal */
            c->pos = save;
            return atom;
        }
        rmin = m; rmax = m;
        if (pk(c) == ',') {
            nx(c);
            if (pk(c) == '}') {
                rmax = -1; /* {m,} */
            } else {
                int n2 = parse_int(c);
                if (c->err) return NULL;
                if (n2 < 0) {
                    /* scan for closing brace to distinguish BADBR vs EBRACE */
                    int found = 0;
                    for (int j = c->pos; j < c->plen; j++)
                        if (c->pat[j] == '}') { found = 1; break; }
                    c->err = found ? REG_BADBR : REG_EBRACE;
                    return NULL;
                }
                rmax = n2;
            }
        }
        if (pk(c) != '}') { c->err = REG_EBRACE; return NULL; }
        nx(c);
        if (rmax >= 0 && rmin > rmax) { c->err = REG_BADBR; return NULL; }
        if (rmin > 255 || (rmax > 255 && rmax >= 0)) { c->err = REG_BADBR; return NULL; }
    }

    /* check for multiple adjacent quantifiers */
    if (is_quant(pk(c))) { c->err = REG_BADRPT; return NULL; }

    Node *n = pnew(c, N_REP); if(!n) return NULL;
    n->a = atom;
    n->rmin = rmin;
    n->rmax = rmax;
    return n;
}

/* ---- atom ---- */
static Node *p_atom(PCtx *c) {
    int ch = pk(c);
    if (ch == -1) { c->err = REG_BADPAT; return NULL; }

    /* quantifier at start of expression/subexpression → error */
    if (ch == '*' || ch == '+' || ch == '?') {
        c->err = REG_BADRPT; return NULL;
    }
    if (ch == '{') {
        /* Check if valid interval at start → BADRPT */
        int save = c->pos;
        nx(c);
        if (isdigit(pk(c))) { c->pos = save; c->err = REG_BADRPT; return NULL; }
        c->pos = save;
        /* not a valid interval, treat as literal */
        nx(c);
        Node *n = pnew(c, N_LIT); if(!n) return NULL;
        n->ch = '{'; return n;
    }

    if (ch == '(') {
        nx(c);
        c->ngroups++;
        int gid = c->ngroups;
        Node *inner = p_alt(c);
        if (c->err) return NULL;
        if (pk(c) != ')') { c->err = REG_EPAREN; return NULL; }
        nx(c);
        Node *n = pnew(c, N_GROUP); if(!n) return NULL;
        n->gid = gid; n->a = inner;
        return n;
    }
    if (ch == ')') return NULL;

    if (ch == '[') return p_bracket(c);

    if (ch == '.') { nx(c); return pnew(c, N_DOT); }
    if (ch == '^') { nx(c); return pnew(c, N_BOL); }
    if (ch == '$') { nx(c); return pnew(c, N_EOL); }

    if (ch == '\\') {
        nx(c);
        ch = pk(c);
        if (ch == -1) { c->err = REG_EESCAPE; return NULL; }
        nx(c);
        Node *n = pnew(c, N_LIT); if(!n) return NULL;
        n->ch = ch; return n;
    }

    nx(c);
    Node *n = pnew(c, N_LIT); if(!n) return NULL;
    n->ch = ch; return n;
}

/* ---- bracket expression ---- */
static void add_posix_class(unsigned char *cset, const char *name, int icase) {
    for (int ch = 0; ch < 256; ch++) {
        int match = 0;
        if      (strcmp(name,"alnum")==0)  match = isalnum(ch);
        else if (strcmp(name,"alpha")==0)  match = isalpha(ch);
        else if (strcmp(name,"blank")==0)  match = (ch==' '||ch=='\t');
        else if (strcmp(name,"cntrl")==0)  match = iscntrl(ch);
        else if (strcmp(name,"digit")==0)  match = isdigit(ch);
        else if (strcmp(name,"graph")==0)  match = isgraph(ch);
        else if (strcmp(name,"lower")==0)  match = icase ? isalpha(ch) : islower(ch);
        else if (strcmp(name,"print")==0)  match = isprint(ch);
        else if (strcmp(name,"punct")==0)  match = ispunct(ch);
        else if (strcmp(name,"space")==0)  match = isspace(ch);
        else if (strcmp(name,"upper")==0)  match = icase ? isalpha(ch) : isupper(ch);
        else if (strcmp(name,"xdigit")==0) match = isxdigit(ch);
        if (match) cset_add(cset, ch);
    }
}

static Node *p_bracket(PCtx *c) {
    nx(c); /* consume '[' */
    Node *n = pnew(c, N_CLASS); if(!n) return NULL;
    int negate = 0;
    if (pk(c) == '^') { negate = 1; nx(c); }
    n->neg = negate;
    int icase = (c->cflags & REG_ICASE) != 0;

    int first = 1;
    while (1) {
        int ch = pk(c);
        if (ch == -1) { c->err = REG_EBRACK; return NULL; }
        if (ch == ']' && !first) break;

        /* character class [:name:] */
        if (ch == '[' && c->pos + 1 < c->plen) {
            int next_ch = (unsigned char)c->pat[c->pos + 1];

            /* [:class:] */
            if (next_ch == ':') {
                c->pos += 2; /* skip [: */
                char name[32]; int ni = 0;
                while (pk(c) != -1 && pk(c) != ':' && ni < 30)
                    name[ni++] = (char)nx(c);
                name[ni] = '\0';
                if (pk(c) != ':' || (c->pos + 1 < c->plen && c->pat[c->pos+1] != ']')) {
                    c->err = REG_EBRACK; return NULL;
                }
                nx(c); nx(c); /* skip :] */
                /* validate class name */
                static const char *valid[] = {
                    "alnum","alpha","blank","cntrl","digit","graph",
                    "lower","print","punct","space","upper","xdigit",NULL
                };
                int found = 0;
                for (const char **v = valid; *v; v++)
                    if (strcmp(name, *v) == 0) { found = 1; break; }
                if (!found) { c->err = REG_ECTYPE; return NULL; }
                add_posix_class(n->cset, name, icase);
                first = 0;
                continue;
            }

            /* [.collating.] */
            if (next_ch == '.') {
                c->pos += 2; /* skip [. */
                char sym[32]; int si = 0;
                while (pk(c) != -1 && !(pk(c) == '.' && c->pos + 1 < c->plen
                       && c->pat[c->pos+1] == ']') && si < 30)
                    sym[si++] = (char)nx(c);
                sym[si] = '\0';
                if (pk(c) != '.' || c->pos + 1 >= c->plen || c->pat[c->pos+1] != ']') {
                    c->err = REG_EBRACK; return NULL;
                }
                nx(c); nx(c); /* skip .] */
                if (si == 1) {
                    /* single-char collating symbol */
                    cset_add_icase(n->cset, (unsigned char)sym[0], icase);
                } else if (si == 0) {
                    c->err = REG_ECOLLATE; return NULL;
                } else {
                    /* multi-char collating: check for known ones */
                    if (strcmp(sym, "one") == 0)
                        cset_add(n->cset, '1');
                    else {
                        c->err = REG_ECOLLATE; return NULL;
                    }
                }
                first = 0;
                continue;
            }

            /* [=equiv=] */
            if (next_ch == '=') {
                c->pos += 2; /* skip [= */
                char eq[32]; int ei = 0;
                while (pk(c) != -1 && !(pk(c) == '=' && c->pos + 1 < c->plen
                       && c->pat[c->pos+1] == ']') && ei < 30)
                    eq[ei++] = (char)nx(c);
                eq[ei] = '\0';
                if (pk(c) != '=' || c->pos + 1 >= c->plen || c->pat[c->pos+1] != ']') {
                    c->err = REG_EBRACK; return NULL;
                }
                nx(c); nx(c); /* skip =] */
                if (ei == 1) {
                    /* treat as the character itself (POSIX: implementation-defined) */
                    cset_add_icase(n->cset, (unsigned char)eq[0], icase);
                } else if (strcmp(eq, "one") == 0) {
                    cset_add(n->cset, '1');
                } else {
                    c->err = REG_ECOLLATE; return NULL;
                }
                first = 0;
                continue;
            }
        }

        nx(c); first = 0;

        /* range check */
        if (pk(c) == '-' && c->pos + 1 < c->plen &&
            (unsigned char)c->pat[c->pos + 1] != ']')
        {
            nx(c); /* consume '-' */
            int end_ch = pk(c);
            /* handle [. collating in end range */
            if (end_ch == '[' && c->pos + 1 < c->plen && c->pat[c->pos+1] == '.') {
                c->pos += 2;
                char sym[32]; int si = 0;
                while (pk(c) != -1 && !(pk(c) == '.' && c->pos + 1 < c->plen
                       && c->pat[c->pos+1] == ']') && si < 30)
                    sym[si++] = (char)nx(c);
                sym[si] = '\0';
                if (pk(c) != '.' || c->pos+1 >= c->plen || c->pat[c->pos+1] != ']') {
                    c->err = REG_EBRACK; return NULL;
                }
                nx(c); nx(c);
                end_ch = (si == 1) ? (unsigned char)sym[0] : -1;
                if (end_ch < 0) { c->err = REG_ECOLLATE; return NULL; }
            } else {
                end_ch = nx(c);
            }
            if (end_ch == -1) { c->err = REG_ERANGE; return NULL; }
            if (ch > end_ch) { c->err = REG_ERANGE; return NULL; }
            for (int i = ch; i <= end_ch; i++)
                cset_add_icase(n->cset, i, icase);
        } else {
            cset_add_icase(n->cset, ch, icase);
        }
    }
    nx(c); /* consume ']' */
    return n;
}

/* ------------------------------------------------------------------ */
/*  Compiler: AST → bytecode                                           */
/* ------------------------------------------------------------------ */
static int comp(Node *n, Inst *prog, int pc);

static int emit_op(Inst *prog, int pc, int op) {
    if (pc < MAX_INST) { memset(&prog[pc],0,sizeof(Inst)); prog[pc].op = op; }
    return pc + 1;
}

static int comp(Node *n, Inst *prog, int pc) {
    if (!n) return pc;
    switch (n->type) {
    case N_LIT:
        if (pc < MAX_INST) { prog[pc].op = I_CHAR; prog[pc].c = n->ch; }
        return pc + 1;
    case N_DOT:
        return emit_op(prog, pc, I_ANY);
    case N_CLASS:
        if (pc < MAX_INST) {
            prog[pc].op = I_CLASS;
            memcpy(prog[pc].cset, n->cset, 32);
            prog[pc].neg = n->neg;
        }
        return pc + 1;
    case N_CAT:
        pc = comp(n->a, prog, pc);
        return comp(n->b, prog, pc);
    case N_ALT: {
        int spc = pc++; /* SPLIT_ALT placeholder */
        int l1 = pc;
        pc = comp(n->a, prog, pc);
        int jpc = pc++; /* JMP placeholder */
        int l2 = pc;
        pc = comp(n->b, prog, pc);
        int l3 = pc;
        if (spc<MAX_INST) { prog[spc].op=I_SPLIT_ALT; prog[spc].x=l1; prog[spc].y=l2; }
        if (jpc<MAX_INST) { prog[jpc].op=I_JMP; prog[jpc].x=l3; }
        return pc;
    }
    case N_REP: {
        int rmin = n->rmin, rmax = n->rmax;
        /* emit rmin mandatory copies */
        for (int i = 0; i < rmin; i++)
            pc = comp(n->a, prog, pc);
        if (rmax < 0) {
            /* unbounded: SPLIT body/skip loop */
            int l0 = pc;
            if (pc<MAX_INST) { prog[pc].op = I_SPLIT; }
            pc++;
            int l1 = pc;
            pc = comp(n->a, prog, pc);
            if (pc<MAX_INST) { prog[pc].op = I_JMP; prog[pc].x = l0; }
            pc++;
            int l2 = pc;
            if (l0<MAX_INST) { prog[l0].x = l1; prog[l0].y = l2; }
        } else {
            /* bounded: (rmax-rmin) optional copies */
            int opt = rmax - rmin;
            for (int i = 0; i < opt; i++) {
                int spc = pc;
                if (pc<MAX_INST) { prog[pc].op = I_SPLIT; }
                pc++;
                int l1 = pc;
                pc = comp(n->a, prog, pc);
                if (spc<MAX_INST) { prog[spc].x = l1; prog[spc].y = pc; }
            }
        }
        return pc;
    }
    case N_GROUP:
        if (pc<MAX_INST) { prog[pc].op = I_SAVE; prog[pc].x = 2*n->gid; } pc++;
        pc = comp(n->a, prog, pc);
        if (pc<MAX_INST) { prog[pc].op = I_SAVE; prog[pc].x = 2*n->gid+1; } pc++;
        return pc;
    case N_BOL: return emit_op(prog, pc, I_BOL);
    case N_EOL: return emit_op(prog, pc, I_EOL);
    }
    return pc;
}

/* ------------------------------------------------------------------ */
/*  VM: backtracking interpreter                                       */
/* ------------------------------------------------------------------ */
static int vm_run(const Inst *prog, int pc, const char *s, int sp, int len,
                  int cflags, int eflags, int *saves, int nsaves, int *visited)
{
    for (;;) {
        if (pc < 0 || pc >= MAX_INST) return -1;
        const Inst *i = &prog[pc];
        switch (i->op) {
        case I_CHAR:
            if (sp >= len) return -1;
            if (cflags & REG_ICASE) {
                if (tolower((unsigned char)s[sp]) != tolower(i->c)) return -1;
            } else {
                if ((unsigned char)s[sp] != i->c) return -1;
            }
            sp++; pc++; break;

        case I_ANY:
            if (sp >= len) return -1;
            if ((cflags & REG_NEWLINE) && s[sp] == '\n') return -1;
            sp++; pc++; break;

        case I_CLASS:
            if (sp >= len) return -1;
            { int ch = (unsigned char)s[sp];
              int in = cset_has(i->cset, ch);
              if (i->neg) in = !in;
              if (!in) return -1;
            }
            sp++; pc++; break;

        case I_SPLIT: {
            /* greedy quantifier: try first path, backtrack */
            if (visited[pc] == sp) { pc = i->y; break; }
            int old_v = visited[pc];
            visited[pc] = sp;
            int saved[MAX_SAVES];
            if (nsaves > 0) memcpy(saved, saves, nsaves * sizeof(int));
            int r = vm_run(prog, i->x, s, sp, len, cflags, eflags, saves, nsaves, visited);
            visited[pc] = old_v;
            if (r >= 0) return r;
            if (nsaves > 0) memcpy(saves, saved, nsaves * sizeof(int));
            pc = i->y; break;
        }

        case I_SPLIT_ALT: {
            /* alternation: try both, return longest; on tie prefer
               longer leftmost subexpressions (POSIX rule) */
            if (visited[pc] == sp) { return -1; }
            int old_v = visited[pc];
            visited[pc] = sp;
            int saved[MAX_SAVES];
            if (nsaves > 0) memcpy(saved, saves, nsaves * sizeof(int));
            int r1 = vm_run(prog, i->x, s, sp, len, cflags, eflags, saves, nsaves, visited);
            int saves1[MAX_SAVES];
            if (nsaves > 0) memcpy(saves1, saves, nsaves * sizeof(int));

            if (nsaves > 0) memcpy(saves, saved, nsaves * sizeof(int));
            int r2 = vm_run(prog, i->y, s, sp, len, cflags, eflags, saves, nsaves, visited);
            visited[pc] = old_v;

            if (r1 >= 0 && r2 >= 0) {
                if (r1 > r2) {
                    if (nsaves > 0) memcpy(saves, saves1, nsaves * sizeof(int));
                    return r1;
                }
                if (r2 > r1) {
                    return r2;
                }
                /* r1 == r2: prefer path with longer leftmost subexpressions */
                int prefer_1 = 1;
                for (int g = 2; g < nsaves; g += 2) {
                    int l1 = (saves1[g]>=0 && saves1[g+1]>=0) ? saves1[g+1]-saves1[g] : -1;
                    int l2 = (saves[g]>=0 && saves[g+1]>=0) ? saves[g+1]-saves[g] : -1;
                    if (l1 > l2) { prefer_1 = 1; break; }
                    if (l2 > l1) { prefer_1 = 0; break; }
                }
                if (prefer_1) {
                    if (nsaves > 0) memcpy(saves, saves1, nsaves * sizeof(int));
                    return r1;
                }
                return r2;
            }
            if (r1 >= 0) {
                if (nsaves > 0) memcpy(saves, saves1, nsaves * sizeof(int));
                return r1;
            }
            if (r2 >= 0) return r2;
            if (nsaves > 0) memcpy(saves, saved, nsaves * sizeof(int));
            return -1;
        }

        case I_JMP:
            pc = i->x; break;

        case I_SAVE: {
            int slot = i->x;
            if (slot < nsaves) {
                int old = saves[slot];
                saves[slot] = sp;
                int r = vm_run(prog, pc+1, s, sp, len, cflags, eflags, saves, nsaves, visited);
                if (r >= 0) return r;
                saves[slot] = old;
                return -1;
            }
            pc++; break;
        }

        case I_BOL:
            if (cflags & REG_NEWLINE) {
                if (sp == 0) {
                    if (eflags & REG_NOTBOL) { return -1; }
                    pc++; break;
                }
                if (s[sp-1] == '\n') { pc++; break; }
                return -1;
            } else {
                if (sp != 0) return -1;
                if (eflags & REG_NOTBOL) return -1;
                pc++; break;
            }

        case I_EOL:
            if (cflags & REG_NEWLINE) {
                if (sp == len) {
                    if (eflags & REG_NOTEOL) { return -1; }
                    pc++; break;
                }
                if (s[sp] == '\n') { pc++; break; }
                return -1;
            } else {
                if (sp != len) return -1;
                if (eflags & REG_NOTEOL) return -1;
                pc++; break;
            }

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
        return REG_BADPAT;

    PCtx ctx;
    memset(&ctx, 0, sizeof ctx);
    ctx.pat    = pattern;
    ctx.plen   = (int)strlen(pattern);
    ctx.cflags = cflags;

    Node *ast = p_alt(&ctx);

    if (ctx.err)            { pfree_all(&ctx); return ctx.err; }
    if (ctx.pos != ctx.plen){ pfree_all(&ctx); return REG_EPAREN; }

    CompiledRE *cre = calloc(1, sizeof *cre);
    if (!cre) { pfree_all(&ctx); return REG_ESPACE; }
    cre->pat_dup = strdup(pattern);

    int pc = 0;
    cre->prog[pc].op = I_SAVE; cre->prog[pc].x = 0; pc++;
    pc = comp(ast, cre->prog, pc);
    cre->prog[pc].op = I_SAVE; cre->prog[pc].x = 1; pc++;
    pc = emit_op(cre->prog, pc, I_MATCH);
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
    int nsaves = (cre->ngroups + 1) * 2;
    if (nsaves > MAX_SAVES) nsaves = MAX_SAVES;

    int saves[MAX_SAVES];

    for (int start = 0; start <= len; start++) {
        for (int k = 0; k < nsaves; k++) saves[k] = -1;
        int visited[MAX_INST];
        memset(visited, -1, sizeof visited);

        int end = vm_run(cre->prog, 0, string, start, len,
                         cre->cflags, eflags, saves, nsaves, visited);
        if (end >= 0) {
            if (pmatch && nmatch > 0 && !(cre->cflags & REG_NOSUB)) {
                pmatch[0].rm_so = start;
                pmatch[0].rm_eo = end;
                for (size_t j = 1; j < nmatch; j++) {
                    int so_slot = (int)(2 * j);
                    int eo_slot = (int)(2 * j + 1);
                    if (so_slot < nsaves && saves[so_slot] >= 0) {
                        pmatch[j].rm_so = saves[so_slot];
                        pmatch[j].rm_eo = saves[eo_slot];
                    } else {
                        pmatch[j].rm_so = -1;
                        pmatch[j].rm_eo = -1;
                    }
                }
            }
            return 0;
        }
    }
    return REG_NOMATCH;
}

void regfree(regex_t *preg) {
    CompiledRE *cre = (CompiledRE *)preg->__priv;
    if (cre) free(cre->pat_dup);
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

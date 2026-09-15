/* DaeDaLus DDL Lexer Specification for Flex */

%{
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

/* Token type constants — must match Python side */
#define TOK_EOF 0
#define TOK_ID 1
#define TOK_INT 2
#define TOK_STR 3
#define TOK_ARROW 10
#define TOK_BIASED 11
#define TOK_DOTDOT 12
#define TOK_LBPIPE 13
#define TOK_RBPIPE 14
#define TOK_LE 15
#define TOK_GE 16
#define TOK_EQEQ 17
#define TOK_DOLLARDOLLAR 18
#define TOK_DOLLAR 19
#define TOK_LP 20
#define TOK_RP 21
#define TOK_LB 22
#define TOK_RB 23
#define TOK_LC 24
#define TOK_RC 25
#define TOK_EQ 26
#define TOK_DOT 27
#define TOK_COL 28
#define TOK_SEMI 29
#define TOK_COMMA 30
#define TOK_LT 31
#define TOK_GT 32
#define TOK_PLUS 33
#define TOK_MINUS 34
#define TOK_STAR 35
#define TOK_AT 36
#define TOK_CARET 37
#define TOK_PIPE 38

/* Token structure passed to Python via ctypes */
typedef struct {
    int type;
    int line;
    int col;
    long long int_val;
    char str_val[1024];
} DDLToken;

static int cur_line = 1;
static int cur_col = 1;
static int tok_line, tok_col;
static DDLToken cur_tok;
static int comment_depth = 0;
static int initialized = 0;

/* Track position before each rule fires */
#define YY_USER_ACTION { \
    tok_line = cur_line; \
    tok_col = cur_col; \
    for (int _yy_i = 0; _yy_i < yyleng; _yy_i++) { \
        if (yytext[_yy_i] == '\n') { cur_line++; cur_col = 1; } \
        else { cur_col++; } \
    } \
}

static void set_tok(int type) {
    cur_tok.type = type;
    cur_tok.line = tok_line;
    cur_tok.col = tok_col;
    cur_tok.int_val = 0;
    cur_tok.str_val[0] = '\0';
}

static void set_tok_str(int type, const char* s) {
    set_tok(type);
    strncpy(cur_tok.str_val, s, sizeof(cur_tok.str_val) - 1);
    cur_tok.str_val[sizeof(cur_tok.str_val) - 1] = '\0';
}

static void set_tok_int(int type, long long v) {
    set_tok(type);
    cur_tok.int_val = v;
}
%}

%option noyywrap nounput noinput

%x BCOMMENT

%%

 /* Nestable block comments using exclusive start condition */
"{-"            { comment_depth = 1; BEGIN(BCOMMENT); }
<BCOMMENT>"{-"  { comment_depth++; }
<BCOMMENT>"-}"  { if (--comment_depth == 0) BEGIN(INITIAL); }
<BCOMMENT>\n    { /* newline tracked by YY_USER_ACTION */ }
<BCOMMENT>.     { /* skip comment content */ }

 /* Line comments */
"--"[^\n]*      { /* skip line comment */ }

 /* Whitespace */
[ \t]+          { /* skip horizontal whitespace */ }
\n              { /* newline tracked by YY_USER_ACTION */ }

 /* Multi-character operators (longest match takes precedence) */
"->"            { set_tok(TOK_ARROW); return TOK_ARROW; }
"<|"            { set_tok(TOK_BIASED); return TOK_BIASED; }
".."            { set_tok(TOK_DOTDOT); return TOK_DOTDOT; }
"{|"            { set_tok(TOK_LBPIPE); return TOK_LBPIPE; }
"|}"            { set_tok(TOK_RBPIPE); return TOK_RBPIPE; }
"<="            { set_tok(TOK_LE); return TOK_LE; }
">="            { set_tok(TOK_GE); return TOK_GE; }
"=="            { set_tok(TOK_EQEQ); return TOK_EQEQ; }
"$$"            { set_tok(TOK_DOLLARDOLLAR); return TOK_DOLLARDOLLAR; }

 /* Special combined tokens: as? and as! */
"as?"           { set_tok_str(TOK_ID, "as?"); return TOK_ID; }
"as!"           { set_tok_str(TOK_ID, "as!"); return TOK_ID; }

 /* String literals with escape handling */
\"([^"\\]|\\.)*\" {
                    char buf[1024];
                    int j = 0;
                    /* skip opening and closing quotes */
                    for (int i = 1; i < yyleng - 1 && j < 1023; i++) {
                        if (yytext[i] == '\\' && i + 1 < yyleng - 1) {
                            i++;
                            buf[j++] = yytext[i];
                        } else {
                            buf[j++] = yytext[i];
                        }
                    }
                    buf[j] = '\0';
                    set_tok_str(TOK_STR, buf);
                    return TOK_STR;
                }

 /* Hexadecimal integers */
0[xX][0-9a-fA-F_]+ {
                    char buf[128];
                    int j = 0;
                    /* skip 0x prefix, strip underscores */
                    for (int i = 2; i < yyleng && j < 127; i++) {
                        if (yytext[i] != '_') buf[j++] = yytext[i];
                    }
                    buf[j] = '\0';
                    set_tok_int(TOK_INT, strtoll(buf, NULL, 16));
                    return TOK_INT;
                }

 /* Decimal integers */
[0-9]+          { set_tok_int(TOK_INT, strtoll(yytext, NULL, 10)); return TOK_INT; }

 /* Identifiers (keywords distinguished on the Python side) */
[a-zA-Z_][a-zA-Z0-9_]* {
                    set_tok_str(TOK_ID, yytext);
                    return TOK_ID;
                }

 /* Single-character operators and delimiters */
"$"             { set_tok(TOK_DOLLAR); return TOK_DOLLAR; }
"("             { set_tok(TOK_LP); return TOK_LP; }
")"             { set_tok(TOK_RP); return TOK_RP; }
"["             { set_tok(TOK_LB); return TOK_LB; }
"]"             { set_tok(TOK_RB); return TOK_RB; }
"{"             { set_tok(TOK_LC); return TOK_LC; }
"}"             { set_tok(TOK_RC); return TOK_RC; }
"="             { set_tok(TOK_EQ); return TOK_EQ; }
"."             { set_tok(TOK_DOT); return TOK_DOT; }
":"             { set_tok(TOK_COL); return TOK_COL; }
";"             { set_tok(TOK_SEMI); return TOK_SEMI; }
","             { set_tok(TOK_COMMA); return TOK_COMMA; }
"<"             { set_tok(TOK_LT); return TOK_LT; }
">"             { set_tok(TOK_GT); return TOK_GT; }
"+"             { set_tok(TOK_PLUS); return TOK_PLUS; }
"-"             { set_tok(TOK_MINUS); return TOK_MINUS; }
"*"             { set_tok(TOK_STAR); return TOK_STAR; }
"@"             { set_tok(TOK_AT); return TOK_AT; }
"^"             { set_tok(TOK_CARET); return TOK_CARET; }
"|"             { set_tok(TOK_PIPE); return TOK_PIPE; }

 /* Skip any unrecognized character */
.               { /* skip */ }

%%

/* ============================================================
 * Public C API for Python ctypes
 * ============================================================ */

void ddl_lexer_init(const char* input) {
    if (initialized) {
        yylex_destroy();
    }
    cur_line = 1;
    cur_col = 1;
    comment_depth = 0;
    yy_scan_string(input);
    initialized = 1;
}

int ddl_lexer_next(DDLToken* tok) {
    int t = yylex();
    if (t == 0) {
        tok->type = TOK_EOF;
        tok->line = cur_line;
        tok->col = cur_col;
        tok->int_val = 0;
        tok->str_val[0] = '\0';
        return TOK_EOF;
    }
    *tok = cur_tok;
    return t;
}

void ddl_lexer_free(void) {
    if (initialized) {
        yylex_destroy();
        initialized = 0;
    }
}

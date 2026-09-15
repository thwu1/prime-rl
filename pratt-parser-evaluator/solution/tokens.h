/* tokens.h -- shared token definitions for flex lexer and Pratt parser */

#ifndef TOKENS_H
#define TOKENS_H

/* Single-character tokens use their ASCII value directly.
 * Multi-char operators and keywords start at 256. */
enum {
    TOK_EOF = 0,
    TOK_NUM = 256,
    TOK_IDENT,
    TOK_LET,
    TOK_IN,
    TOK_IF,
    TOK_THEN,
    TOK_ELSE,
    TOK_FN,
    TOK_OPERATOR,
    TOK_INFIXL,
    TOK_INFIXR,
    TOK_PREFIX,
    TOK_STARSTAR,   /* ** */
    TOK_EQEQ,       /* == */
    TOK_NE,          /* != */
    TOK_LE,          /* <= */
    TOK_GE,          /* >= */
    TOK_SHL,         /* << */
    TOK_SHR,         /* >> */
    TOK_LAND,        /* && */
    TOK_LOR,         /* || */
};

typedef struct {
    long long ival;
    char sval[256];
} TokenValue;

extern TokenValue yylval;
extern int yylex(void);

#endif /* TOKENS_H */

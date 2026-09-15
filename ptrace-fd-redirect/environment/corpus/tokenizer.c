#include <stdio.h>
#include <ctype.h>
#include <string.h>

typedef enum {
    TOK_IDENT,
    TOK_NUMBER,
    TOK_STRING,
    TOK_SYMBOL,
    TOK_EOF
} TokenType;

typedef struct {
    TokenType type;
    const char *start;
    size_t len;
    int line;
} Token;

typedef struct {
    const char *src;
    size_t pos;
    int line;
} Lexer;

void lexer_init(Lexer *lex, const char *src) {
    lex->src = src;
    lex->pos = 0;
    lex->line = 1;
}

static void skip_whitespace(Lexer *lex) {
    while (lex->src[lex->pos]) {
        if (lex->src[lex->pos] == '\n') {
            lex->line++;
            lex->pos++;
        } else if (isspace(lex->src[lex->pos])) {
            lex->pos++;
        } else {
            break;
        }
    }
}

Token lexer_next(Lexer *lex) {
    skip_whitespace(lex);
    Token tok;
    tok.line = lex->line;
    tok.start = lex->src + lex->pos;

    if (!lex->src[lex->pos]) {
        tok.type = TOK_EOF;
        tok.len = 0;
        return tok;
    }

    if (isalpha(lex->src[lex->pos]) || lex->src[lex->pos] == '_') {
        tok.type = TOK_IDENT;
        while (isalnum(lex->src[lex->pos]) || lex->src[lex->pos] == '_')
            lex->pos++;
        tok.len = (lex->src + lex->pos) - tok.start;
    } else if (isdigit(lex->src[lex->pos])) {
        tok.type = TOK_NUMBER;
        while (isdigit(lex->src[lex->pos]))
            lex->pos++;
        tok.len = (lex->src + lex->pos) - tok.start;
    } else {
        tok.type = TOK_SYMBOL;
        tok.len = 1;
        lex->pos++;
    }
    return tok;
}

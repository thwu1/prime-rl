%{
/* lexer.l -- flex specification for MiniPratt tokenizer */

#include "tokens.h"
#include <string.h>
#include <stdlib.h>
TokenValue yylval;
%}

%option noyywrap nounput noinput

%%

"//"[^\n]*          { /* skip line comments */ }
[ \t\n\r]+          { /* skip whitespace */ }

[0-9]+              { yylval.ival = atoll(yytext); return TOK_NUM; }

"**"                { return TOK_STARSTAR; }
"=="                { return TOK_EQEQ; }
"!="                { return TOK_NE; }
"<="                { return TOK_LE; }
">="                { return TOK_GE; }
"<<"                { return TOK_SHL; }
">>"                { return TOK_SHR; }
"&&"                { return TOK_LAND; }
"||"                { return TOK_LOR; }

"let"               { return TOK_LET; }
"in"                { return TOK_IN; }
"if"                { return TOK_IF; }
"then"              { return TOK_THEN; }
"else"              { return TOK_ELSE; }
"fn"                { return TOK_FN; }
"operator"          { return TOK_OPERATOR; }
"infixl"            { return TOK_INFIXL; }
"infixr"            { return TOK_INFIXR; }
"prefix"            { return TOK_PREFIX; }
"true"              { yylval.ival = 1; return TOK_NUM; }
"false"             { yylval.ival = 0; return TOK_NUM; }

[a-zA-Z_][a-zA-Z0-9_]*  {
    strncpy(yylval.sval, yytext, 255);
    yylval.sval[255] = '\0';
    return TOK_IDENT;
}

[+\-*/%<>&|^~!?:()=;,]  { return yytext[0]; }

.                   { fprintf(stderr, "Unexpected character: %c\n", yytext[0]); exit(1); }

%%

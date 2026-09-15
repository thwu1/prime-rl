
%{
#include "parser.tab.h"
#include <stdlib.h>
#include <string.h>
%}

%option yylineno

%%

"func"      { return FUNC; }
"if"        { return IF; }
"else"      { return ELSE; }
"while"     { return WHILE; }
"return"    { return RETURN; }
"print"     { return PRINT; }
"true"      { yylval.ival = 1; return INT_LIT; }
"false"     { yylval.ival = 0; return INT_LIT; }

[0-9]+      { yylval.ival = atoi(yytext); return INT_LIT; }
[a-zA-Z_][a-zA-Z0-9_]*  { yylval.sval = strdup(yytext); return IDENT; }

"=="        { return EQ; }
"!="        { return NEQ; }
"<="        { return LEQ; }
">="        { return GEQ; }
"&&"        { return AND; }
"||"        { return OR; }
"+"         { return PLUS; }
"-"         { return MINUS; }
"*"         { return STAR; }
"/"         { return SLASH; }
"%"         { return PERCENT; }
"<"         { return LT; }
">"         { return GT; }
"!"         { return NOT; }
"="         { return ASSIGN; }
"("         { return LPAREN; }
")"         { return RPAREN; }
"{"         { return LBRACE; }
"}"         { return RBRACE; }
","         { return COMMA; }
";"         { return SEMI; }

[ \t\r\n]+  { /* skip whitespace */ }
"//"[^\n]*  { /* skip line comments */ }

.           { fprintf(stderr, "Lexer error: unexpected '%s' at line %d\n", yytext, yylineno); }

%%

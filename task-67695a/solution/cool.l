%{

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int comment_depth = 0;
static char str_buf[4096];
static int str_len = 0;

static void str_add(char c) {
    if (str_len < 4095) str_buf[str_len++] = c;
}

static void emit_str(void) {
    int i;
    printf("STR_CONST ");
    for (i = 0; i < str_len; i++) {
        unsigned char c = (unsigned char)str_buf[i];
        switch (c) {
            case '\n': printf("\\n"); break;
            case '\t': printf("\\t"); break;
            case '\b': printf("\\b"); break;
            case '\f': printf("\\f"); break;
            case '\\': printf("\\\\"); break;
            case '\r': printf("\\r"); break;
            default:   putchar(c); break;
        }
    }
    printf("\n");
}
%}

%option noyywrap nounput noinput

%x COMMENT STRING LINE_COMMENT

%%

"(*"                        { comment_depth = 1; BEGIN(COMMENT); }
<COMMENT>"(*"               { comment_depth++; }
<COMMENT>"*)"               { if (--comment_depth == 0) BEGIN(INITIAL); }
<COMMENT>\n                 { /* skip */ }
<COMMENT>.                  { /* skip */ }
<COMMENT><<EOF>>            { fprintf(stderr, "Error: EOF in comment\n"); exit(1); }

"--"                        { BEGIN(LINE_COMMENT); }
<LINE_COMMENT>\n            { BEGIN(INITIAL); }
<LINE_COMMENT>.             { /* skip */ }

\"                          { str_len = 0; BEGIN(STRING); }
<STRING>\"                  { emit_str(); BEGIN(INITIAL); }
<STRING>\\n                 { str_add('\n'); }
<STRING>\\t                 { str_add('\t'); }
<STRING>\\b                 { str_add('\b'); }
<STRING>\\f                 { str_add('\f'); }
<STRING>\\\\                { str_add('\\'); }
<STRING>\\\"                { str_add('"'); }
<STRING>\\\n                { str_add('\n'); }
<STRING>\\[^\0]             { str_add(yytext[1]); }
<STRING>\n                  { fprintf(stderr, "Error: unterminated string\n"); exit(1); }
<STRING><<EOF>>             { fprintf(stderr, "Error: EOF in string\n"); exit(1); }
<STRING>.                   { str_add(yytext[0]); }

[ \t\r\n\f\v]+             { /* skip whitespace */ }

[cC][lL][aA][sS][sS]                           { printf("CLASS\n"); }
[eE][lL][sS][eE]                               { printf("ELSE\n"); }
[fF][iI]                                        { printf("FI\n"); }
[iI][fF]                                        { printf("IF\n"); }
[iI][nN]                                        { printf("IN\n"); }
[iI][nN][hH][eE][rR][iI][tT][sS]               { printf("INHERITS\n"); }
[iI][sS][vV][oO][iI][dD]                        { printf("ISVOID\n"); }
[lL][eE][tT]                                    { printf("LET\n"); }
[lL][oO][oO][pP]                                { printf("LOOP\n"); }
[pP][oO][oO][lL]                                { printf("POOL\n"); }
[nN][eE][wW]                                    { printf("NEW\n"); }
[oO][fF]                                        { printf("OF\n"); }
[nN][oO][tT]                                    { printf("NOT\n"); }
[tT][hH][eE][nN]                                { printf("THEN\n"); }
[wW][hH][iI][lL][eE]                            { printf("WHILE\n"); }
[cC][aA][sS][eE]                                { printf("CASE\n"); }
[eE][sS][aA][cC]                                { printf("ESAC\n"); }

t[rR][uU][eE]              { printf("BOOL_CONST true\n"); }
f[aA][lL][sS][eE]          { printf("BOOL_CONST false\n"); }

[0-9]+                      { printf("INT_CONST %s\n", yytext); }
[A-Z][a-zA-Z0-9_]*         { printf("TYPEID %s\n", yytext); }
[a-z][a-zA-Z0-9_]*         { printf("OBJECTID %s\n", yytext); }

"=>"                        { printf("DARROW\n"); }
"<="                        { printf("LE\n"); }
"<-"                        { printf("ASSIGN\n"); }

"+"                         { printf("PLUS\n"); }
"-"                         { printf("MINUS\n"); }
"*"                         { printf("TIMES\n"); }
"/"                         { printf("DIVIDE\n"); }
"<"                         { printf("LT\n"); }
"="                         { printf("EQ\n"); }
"~"                         { printf("TILDE\n"); }
"@"                         { printf("AT\n"); }
"."                         { printf("DOT\n"); }
"("                         { printf("LPAREN\n"); }
")"                         { printf("RPAREN\n"); }
"{"                         { printf("LBRACE\n"); }
"}"                         { printf("RBRACE\n"); }
";"                         { printf("SEMI\n"); }
":"                         { printf("COLON\n"); }
","                         { printf("COMMA\n"); }

.                           { fprintf(stderr, "Error: unexpected character '%c'\n", yytext[0]); }

%%

int main(int argc, char **argv) {
    if (argc > 1) {
        FILE *f = fopen(argv[1], "r");
        if (!f) {
            perror(argv[1]);
            return 1;
        }
        yyin = f;
    }
    yylex();
    printf("EOF\n");
    return 0;
}

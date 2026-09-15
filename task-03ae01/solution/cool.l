/*
 * Flex lexer specification for the Cool programming language.
 * Outputs one JSON token object per line to stdout.
 *
 */

%option noyywrap
%option yylineno

%{
#include <stdio.h>
#include <string.h>
#include "json_escape.h"

#define MAX_STR_CONST 1025

static char string_buf[MAX_STR_CONST];
static int string_buf_len = 0;
static int comment_depth = 0;
static int string_error = 0;
%}

%x COMMENT
%x LINE_COMMENT
%x COOL_STRING

DIGIT    [0-9]
LETTER   [a-zA-Z]

%%

 /* ---- Keywords (case-insensitive) ---- */
(?i:class)    { printf("{\"type\":\"CLASS\",\"line\":%d}\n", yylineno); }
(?i:else)     { printf("{\"type\":\"ELSE\",\"line\":%d}\n", yylineno); }
(?i:fi)       { printf("{\"type\":\"FI\",\"line\":%d}\n", yylineno); }
(?i:if)       { printf("{\"type\":\"IF\",\"line\":%d}\n", yylineno); }
(?i:in)       { printf("{\"type\":\"IN\",\"line\":%d}\n", yylineno); }
(?i:inherits) { printf("{\"type\":\"INHERITS\",\"line\":%d}\n", yylineno); }
(?i:let)      { printf("{\"type\":\"LET\",\"line\":%d}\n", yylineno); }
(?i:loop)     { printf("{\"type\":\"LOOP\",\"line\":%d}\n", yylineno); }
(?i:pool)     { printf("{\"type\":\"POOL\",\"line\":%d}\n", yylineno); }
(?i:then)     { printf("{\"type\":\"THEN\",\"line\":%d}\n", yylineno); }
(?i:while)    { printf("{\"type\":\"WHILE\",\"line\":%d}\n", yylineno); }
(?i:case)     { printf("{\"type\":\"CASE\",\"line\":%d}\n", yylineno); }
(?i:esac)     { printf("{\"type\":\"ESAC\",\"line\":%d}\n", yylineno); }
(?i:of)       { printf("{\"type\":\"OF\",\"line\":%d}\n", yylineno); }
(?i:new)      { printf("{\"type\":\"NEW\",\"line\":%d}\n", yylineno); }
(?i:isvoid)   { printf("{\"type\":\"ISVOID\",\"line\":%d}\n", yylineno); }
(?i:not)      { printf("{\"type\":\"NOT\",\"line\":%d}\n", yylineno); }

 /* ---- Multi-character operators ---- */
"=>"  { printf("{\"type\":\"DARROW\",\"line\":%d}\n", yylineno); }
"<-"  { printf("{\"type\":\"ASSIGN\",\"line\":%d}\n", yylineno); }
"<="  { printf("{\"type\":\"LE\",\"line\":%d}\n", yylineno); }

 /* ---- Boolean constants (first letter MUST be lowercase) ---- */
t(?i:rue)   { printf("{\"type\":\"BOOL_CONST\",\"value\":true,\"line\":%d}\n", yylineno); }
f(?i:alse)  { printf("{\"type\":\"BOOL_CONST\",\"value\":false,\"line\":%d}\n", yylineno); }

 /* ---- Integer constants ---- */
{DIGIT}+ {
    printf("{\"type\":\"INT_CONST\",\"value\":\"%s\",\"line\":%d}\n", yytext, yylineno);
}

 /* ---- Type identifiers (start with uppercase) ---- */
[A-Z]({LETTER}|{DIGIT}|_)* {
    printf("{\"type\":\"TYPEID\",\"value\":\"%s\",\"line\":%d}\n", yytext, yylineno);
}

 /* ---- Object identifiers (start with lowercase) ---- */
[a-z]({LETTER}|{DIGIT}|_)* {
    printf("{\"type\":\"OBJECTID\",\"value\":\"%s\",\"line\":%d}\n", yytext, yylineno);
}

 /* ---- Nested block comments ---- */
"(*" {
    comment_depth = 1;
    BEGIN(COMMENT);
}

<COMMENT>"(*" { comment_depth++; }

<COMMENT>"*)" {
    comment_depth--;
    if (comment_depth == 0) BEGIN(INITIAL);
}

<COMMENT>\n   { /* yylineno updated automatically */ }
<COMMENT>.    { }

<COMMENT><<EOF>> {
    printf("{\"type\":\"ERROR\",\"value\":\"EOF in comment\",\"line\":%d}\n", yylineno);
    yyterminate();
}

 /* Unmatched close-comment in INITIAL state */
"*)" {
    printf("{\"type\":\"ERROR\",\"value\":\"Unmatched *)\",\"line\":%d}\n", yylineno);
}

 /* ---- Single-line comments ---- */
"--"              { BEGIN(LINE_COMMENT); }
<LINE_COMMENT>\n  { BEGIN(INITIAL); }
<LINE_COMMENT>.   { }
<LINE_COMMENT><<EOF>> { yyterminate(); }

 /* ---- String constants ---- */
\" {
    string_buf_len = 0;
    string_error = 0;
    BEGIN(COOL_STRING);
}

<COOL_STRING>\" {
    if (!string_error) {
        printf("{\"type\":\"STR_CONST\",\"value\":");
        json_print_escaped(stdout, string_buf, string_buf_len);
        printf(",\"line\":%d}\n", yylineno);
    }
    BEGIN(INITIAL);
}

<COOL_STRING>\n {
    if (!string_error) {
        printf("{\"type\":\"ERROR\",\"value\":\"Unterminated string constant\",\"line\":%d}\n", yylineno);
    }
    string_error = 0;
    BEGIN(INITIAL);
}

<COOL_STRING><<EOF>> {
    printf("{\"type\":\"ERROR\",\"value\":\"EOF in string constant\",\"line\":%d}\n", yylineno);
    yyterminate();
}

<COOL_STRING>\0 {
    if (!string_error) {
        printf("{\"type\":\"ERROR\",\"value\":\"String contains null character\",\"line\":%d}\n", yylineno);
        string_error = 1;
    }
}

 /* Named escape sequences */
<COOL_STRING>"\\n" {
    if (!string_error) {
        if (string_buf_len + 1 >= MAX_STR_CONST) {
            printf("{\"type\":\"ERROR\",\"value\":\"String constant too long\",\"line\":%d}\n", yylineno);
            string_error = 1;
        } else {
            string_buf[string_buf_len++] = '\n';
        }
    }
}

<COOL_STRING>"\\t" {
    if (!string_error) {
        if (string_buf_len + 1 >= MAX_STR_CONST) {
            printf("{\"type\":\"ERROR\",\"value\":\"String constant too long\",\"line\":%d}\n", yylineno);
            string_error = 1;
        } else {
            string_buf[string_buf_len++] = '\t';
        }
    }
}

<COOL_STRING>"\\b" {
    if (!string_error) {
        if (string_buf_len + 1 >= MAX_STR_CONST) {
            printf("{\"type\":\"ERROR\",\"value\":\"String constant too long\",\"line\":%d}\n", yylineno);
            string_error = 1;
        } else {
            string_buf[string_buf_len++] = '\b';
        }
    }
}

<COOL_STRING>"\\f" {
    if (!string_error) {
        if (string_buf_len + 1 >= MAX_STR_CONST) {
            printf("{\"type\":\"ERROR\",\"value\":\"String constant too long\",\"line\":%d}\n", yylineno);
            string_error = 1;
        } else {
            string_buf[string_buf_len++] = '\f';
        }
    }
}

 /* Escaped newline (backslash at end of line) */
<COOL_STRING>\\\n {
    if (!string_error) {
        if (string_buf_len + 1 >= MAX_STR_CONST) {
            printf("{\"type\":\"ERROR\",\"value\":\"String constant too long\",\"line\":%d}\n", yylineno);
            string_error = 1;
        } else {
            string_buf[string_buf_len++] = '\n';
        }
    }
}

 /* Generic escape: backslash followed by any character */
<COOL_STRING>\\. {
    if (!string_error) {
        if (string_buf_len + 1 >= MAX_STR_CONST) {
            printf("{\"type\":\"ERROR\",\"value\":\"String constant too long\",\"line\":%d}\n", yylineno);
            string_error = 1;
        } else {
            string_buf[string_buf_len++] = yytext[1];
        }
    }
}

 /* Normal string characters (batch for efficiency) */
<COOL_STRING>[^\\\"\n\0]+ {
    if (!string_error) {
        int len = yyleng;
        if (string_buf_len + len >= MAX_STR_CONST) {
            printf("{\"type\":\"ERROR\",\"value\":\"String constant too long\",\"line\":%d}\n", yylineno);
            string_error = 1;
        } else {
            memcpy(string_buf + string_buf_len, yytext, len);
            string_buf_len += len;
        }
    }
}

 /* ---- Single-character tokens ---- */
"{"   { printf("{\"type\":\"{\",\"line\":%d}\n", yylineno); }
"}"   { printf("{\"type\":\"}\",\"line\":%d}\n", yylineno); }
"("   { printf("{\"type\":\"(\",\"line\":%d}\n", yylineno); }
")"   { printf("{\"type\":\")\",\"line\":%d}\n", yylineno); }
";"   { printf("{\"type\":\";\",\"line\":%d}\n", yylineno); }
":"   { printf("{\"type\":\":\",\"line\":%d}\n", yylineno); }
"."   { printf("{\"type\":\".\",\"line\":%d}\n", yylineno); }
","   { printf("{\"type\":\",\",\"line\":%d}\n", yylineno); }
"@"   { printf("{\"type\":\"@\",\"line\":%d}\n", yylineno); }
"~"   { printf("{\"type\":\"~\",\"line\":%d}\n", yylineno); }
"+"   { printf("{\"type\":\"+\",\"line\":%d}\n", yylineno); }
"-"   { printf("{\"type\":\"-\",\"line\":%d}\n", yylineno); }
"*"   { printf("{\"type\":\"*\",\"line\":%d}\n", yylineno); }
"/"   { printf("{\"type\":\"/\",\"line\":%d}\n", yylineno); }
"<"   { printf("{\"type\":\"<\",\"line\":%d}\n", yylineno); }
"="   { printf("{\"type\":\"=\",\"line\":%d}\n", yylineno); }

 /* ---- Whitespace (ignored) ---- */
[ \t\r\f\v]+  { }
\n            { }

 /* ---- Catch-all: unrecognized character ---- */
. {
    printf("{\"type\":\"ERROR\",\"value\":");
    json_print_escaped(stdout, yytext, yyleng);
    printf(",\"line\":%d}\n", yylineno);
}

%%

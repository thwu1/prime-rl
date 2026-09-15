%{

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int temp_counter = 0;
static int label_counter = 0;

static char* new_temp(void) {
    char *buf = (char*)malloc(16);
    sprintf(buf, "_t%d", temp_counter++);
    return buf;
}

static char* new_label(void) {
    char *buf = (char*)malloc(16);
    sprintf(buf, "_L%d", label_counter++);
    return buf;
}

#define LABEL_STACK_MAX 64
static char *label_stack[LABEL_STACK_MAX];
static int label_sp = 0;
static void push_label(char *l) { label_stack[label_sp++] = l; }
static char* pop_label(void) { return label_stack[--label_sp]; }

#define MAX_CALL_ARGS 32
static char *call_args_buf[MAX_CALL_ARGS];
static int num_call_args = 0;

extern int yylex(void);
extern int yylineno;
void yyerror(const char *s);
%}

%union {
    int ival;
    char *sval;
}

%token <ival> INT_LIT
%token <sval> IDENT
%token FUNC IF ELSE WHILE RETURN PRINT
%token PLUS MINUS STAR SLASH PERCENT
%token EQ NEQ LT GT LEQ GEQ AND OR NOT
%token ASSIGN LPAREN RPAREN LBRACE RBRACE COMMA SEMI

%type <sval> expr

%%

program: func_list ;

func_list: func
         | func_list func
         ;

func: FUNC IDENT LPAREN {
        printf("FUNC %s:\n", $2);
        temp_counter = 0;
    } params RPAREN LBRACE stmts RBRACE {
        printf("  RETURN\nEND FUNC\n");
    }
    ;

params: /* empty */
      | param_list
      ;

param_list: IDENT { printf("  PARAM %s\n", $1); }
          | param_list COMMA IDENT { printf("  PARAM %s\n", $3); }
          ;

stmts: /* empty */
     | stmts stmt
     ;

stmt: IDENT ASSIGN expr SEMI {
        printf("  %s = %s\n", $1, $3);
    }
    | PRINT expr SEMI {
        printf("  PRINT %s\n", $2);
    }
    | RETURN expr SEMI {
        printf("  RETURN %s\n", $2);
    }
    | RETURN SEMI {
        printf("  RETURN\n");
    }
    | IF LPAREN expr RPAREN {
        char *lbl = new_label();
        printf("  IFFALSE %s GOTO %s\n", $3, lbl);
        push_label(lbl);
    } LBRACE stmts RBRACE else_clause
    | WHILE {
        char *top = new_label();
        printf("  LABEL %s\n", top);
        push_label(top);
    } LPAREN expr RPAREN {
        char *end = new_label();
        printf("  IFFALSE %s GOTO %s\n", $4, end);
        push_label(end);
    } LBRACE stmts RBRACE {
        char *end = pop_label();
        char *top = pop_label();
        printf("  GOTO %s\n", top);
        printf("  LABEL %s\n", end);
    }
    | expr SEMI {
        /* expression statement — result discarded */
    }
    ;

else_clause: /* empty */ {
        char *lbl = pop_label();
        printf("  LABEL %s\n", lbl);
    }
    | ELSE {
        char *end_lbl = new_label();
        char *false_lbl = pop_label();
        printf("  GOTO %s\n", end_lbl);
        printf("  LABEL %s\n", false_lbl);
        push_label(end_lbl);
    } LBRACE stmts RBRACE {
        char *end = pop_label();
        printf("  LABEL %s\n", end);
    }
    ;

expr: expr PLUS expr {
        char *t = new_temp();
        printf("  %s = %s + %s\n", t, $1, $3);
        $$ = t;
    }
    | expr MINUS expr {
        char *t = new_temp();
        printf("  %s = %s - %s\n", t, $1, $3);
        $$ = t;
    }
    | expr STAR expr {
        char *t = new_temp();
        printf("  %s = %s * %s\n", t, $1, $3);
        $$ = t;
    }
    | expr SLASH expr {
        char *t = new_temp();
        printf("  %s = %s / %s\n", t, $1, $3);
        $$ = t;
    }
    | expr PERCENT expr {
        char *t = new_temp();
        printf("  %s = %s %% %s\n", t, $1, $3);
        $$ = t;
    }
    | expr EQ expr {
        char *t = new_temp();
        printf("  %s = %s == %s\n", t, $1, $3);
        $$ = t;
    }
    | expr NEQ expr {
        char *t = new_temp();
        printf("  %s = %s != %s\n", t, $1, $3);
        $$ = t;
    }
    | expr LT expr {
        char *t = new_temp();
        printf("  %s = %s < %s\n", t, $1, $3);
        $$ = t;
    }
    | expr GT expr {
        char *t = new_temp();
        printf("  %s = %s > %s\n", t, $1, $3);
        $$ = t;
    }
    | expr LEQ expr {
        char *t = new_temp();
        printf("  %s = %s <= %s\n", t, $1, $3);
        $$ = t;
    }
    | expr GEQ expr {
        char *t = new_temp();
        printf("  %s = %s >= %s\n", t, $1, $3);
        $$ = t;
    }
    | expr AND expr {
        char *t = new_temp();
        printf("  %s = %s && %s\n", t, $1, $3);
        $$ = t;
    }
    | expr OR expr {
        char *t = new_temp();
        printf("  %s = %s || %s\n", t, $1, $3);
        $$ = t;
    }
    | MINUS expr {
        char *t = new_temp();
        printf("  %s = - %s\n", t, $2);
        $$ = t;
    }
    | NOT expr {
        char *t = new_temp();
        printf("  %s = ! %s\n", t, $2);
        $$ = t;
    }
    | LPAREN expr RPAREN {
        $$ = $2;
    }
    | INT_LIT {
        char *t = new_temp();
        printf("  %s = %d\n", t, $1);
        $$ = t;
    }
    | IDENT {
        $$ = $1;
    }
    | IDENT LPAREN {
        num_call_args = 0;
    } call_args RPAREN {
        char *t = new_temp();
        int i;
        printf("  %s = CALL %s", t, $1);
        for (i = 0; i < num_call_args; i++) {
            printf(" %s", call_args_buf[i]);
        }
        printf("\n");
        $$ = t;
    }
    ;

call_args: /* empty */
         | call_arg_list
         ;

call_arg_list: expr {
        call_args_buf[num_call_args++] = $1;
    }
    | call_arg_list COMMA expr {
        call_args_buf[num_call_args++] = $3;
    }
    ;

%%

void yyerror(const char *s) {
    fprintf(stderr, "Parse error: %s at line %d\n", s, yylineno);
    exit(1);
}

int main(void) {
    return yyparse();
}

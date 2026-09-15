%{
open Ast
%}

%token <int> INT
%token <string> IDENT
%token TRUE FALSE
%token PLUS MINUS TIMES DIV
%token EQ NEQ LT LE GT GE
%token AND OR
%token LPAREN RPAREN
%token LET EQUAL IN
%token IF THEN ELSE
%token FUN ARROW
%token SEMICOLON
%token EOF

%nonassoc IN ELSE
%right ARROW
%right SEMICOLON
%left OR
%left AND
%nonassoc EQ NEQ
%nonassoc LT LE GT GE
%left PLUS MINUS
%left TIMES DIV
%nonassoc UMINUS

%start <Ast.expr> program

%%

program:
  | e = expr; EOF { e }

expr:
  | LET; x = IDENT; EQUAL; e1 = expr; IN; e2 = expr
    { Let (x, e1, e2) }
  | IF; e1 = expr; THEN; e2 = expr; ELSE; e3 = expr
    { If (e1, e2, e3) }
  | FUN; x = IDENT; ARROW; e = expr
    { Fun (x, e) }
  | e1 = expr; SEMICOLON; e2 = expr
    { Seq (e1, e2) }
  | e1 = expr; PLUS; e2 = expr
    { BinOp (Add, e1, e2) }
  | e1 = expr; MINUS; e2 = expr
    { BinOp (Sub, e1, e2) }
  | e1 = expr; TIMES; e2 = expr
    { BinOp (Mul, e1, e2) }
  | e1 = expr; DIV; e2 = expr
    { BinOp (Div, e1, e2) }
  | e1 = expr; EQ; e2 = expr
    { BinOp (Eq, e1, e2) }
  | e1 = expr; NEQ; e2 = expr
    { BinOp (Ne, e1, e2) }
  | e1 = expr; LT; e2 = expr
    { BinOp (Lt, e1, e2) }
  | e1 = expr; LE; e2 = expr
    { BinOp (Le, e1, e2) }
  | e1 = expr; GT; e2 = expr
    { BinOp (Gt, e1, e2) }
  | e1 = expr; GE; e2 = expr
    { BinOp (Ge, e1, e2) }
  | e1 = expr; AND; e2 = expr
    { BinOp (And, e1, e2) }
  | e1 = expr; OR; e2 = expr
    { BinOp (Or, e1, e2) }
  | MINUS; e = expr %prec UMINUS
    { UnaryMinus e }
  | e = app_expr
    { e }

app_expr:
  | f = app_expr; a = atom_expr
    { App (f, a) }
  | e = atom_expr
    { e }

atom_expr:
  | i = INT
    { Int i }
  | TRUE
    { Bool true }
  | FALSE
    { Bool false }
  | x = IDENT
    { Var x }
  | LPAREN; e = expr; RPAREN
    { e }

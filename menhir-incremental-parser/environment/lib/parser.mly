(* Broken MiniML parser - has numerous shift/reduce conflicts *)
(* The flat grammar structure and missing precedence declarations *)
(* cause the build to fail. *)

%{
open Ast
%}

%token <int> INT
%token <string> IDENT
%token TRUE FALSE
%token PLUS MINUS TIMES DIV
%token EQ NEQ LT GT LE GE
%token AMPAMP BARBAR
%token NOT
%token LET REC IN
%token IF THEN ELSE
%token FUN ARROW
%token MATCH WITH BAR
%token LPAREN RPAREN LBRACKET RBRACKET
%token COMMA SEMI COLONCOLON
%token UNDERSCORE
%token EOF

(* Only partial precedence - missing comparison, logical, cons, unary *)
%left PLUS MINUS
%left TIMES DIV

%start <Ast.expr> program

%%

program:
  | e = expr; EOF { e }

(* Everything in one flat rule - creates massive conflicts *)
expr:
  | i = INT
      { EInt i }
  | TRUE
      { EBool true }
  | FALSE
      { EBool false }
  | x = IDENT
      { EVar x }
  | e1 = expr; PLUS; e2 = expr
      { EBinOp (Add, e1, e2) }
  | e1 = expr; MINUS; e2 = expr
      { EBinOp (Sub, e1, e2) }
  | e1 = expr; TIMES; e2 = expr
      { EBinOp (Mul, e1, e2) }
  | e1 = expr; DIV; e2 = expr
      { EBinOp (Div, e1, e2) }
  | e1 = expr; EQ; e2 = expr
      { EBinOp (Eq, e1, e2) }
  | e1 = expr; NEQ; e2 = expr
      { EBinOp (Neq, e1, e2) }
  | e1 = expr; LT; e2 = expr
      { EBinOp (Lt, e1, e2) }
  | e1 = expr; GT; e2 = expr
      { EBinOp (Gt, e1, e2) }
  | e1 = expr; LE; e2 = expr
      { EBinOp (Le, e1, e2) }
  | e1 = expr; GE; e2 = expr
      { EBinOp (Ge, e1, e2) }
  | e1 = expr; AMPAMP; e2 = expr
      { EBinOp (And, e1, e2) }
  | e1 = expr; BARBAR; e2 = expr
      { EBinOp (Or, e1, e2) }
  | MINUS; e = expr
      { EUnOp (Neg, e) }
  | NOT; e = expr
      { EUnOp (Not, e) }
  | LET; x = IDENT; EQ; e1 = expr; IN; e2 = expr
      { ELet (x, e1, e2) }
  | LET; REC; f = IDENT; x = IDENT; EQ; e1 = expr; IN; e2 = expr
      { ELetRec (f, x, e1, e2) }
  | IF; e1 = expr; THEN; e2 = expr; ELSE; e3 = expr
      { EIf (e1, e2, e3) }
  | FUN; x = IDENT; ARROW; e = expr
      { EFun (x, e) }
  | e1 = expr; e2 = expr
      { EApp (e1, e2) }
  | LPAREN; e = expr; RPAREN
      { e }
  | LPAREN; e = expr; COMMA; es = separated_nonempty_list(COMMA, expr); RPAREN
      { ETuple (e :: es) }
  | LBRACKET; es = separated_list(SEMI, expr); RBRACKET
      { EList es }
  | e1 = expr; COLONCOLON; e2 = expr
      { ECons (e1, e2) }
  | MATCH; e = expr; WITH; bs = cases
      { EMatch (e, bs) }
  | e1 = expr; SEMI; e2 = expr
      { ESeq (e1, e2) }

cases:
  | option(BAR); p = pattern; ARROW; e = expr
      { [(p, e)] }
  | cs = cases; BAR; p = pattern; ARROW; e = expr
      { cs @ [(p, e)] }

pattern:
  | UNDERSCORE
      { PWild }
  | x = IDENT
      { PVar x }
  | i = INT
      { PInt i }
  | TRUE
      { PBool true }
  | FALSE
      { PBool false }
  | LPAREN; p = pattern; COMMA; ps = separated_nonempty_list(COMMA, pattern); RPAREN
      { PTuple (p :: ps) }
  | LBRACKET; ps = separated_list(SEMI, pattern); RBRACKET
      { PList ps }
  | p1 = pattern; COLONCOLON; p2 = pattern
      { PCons (p1, p2) }

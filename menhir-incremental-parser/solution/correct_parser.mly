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

(* Precedence declarations for conflict resolution *)
(* lower position = lower precedence *)
%nonassoc below_SEMI
%right    SEMI
%nonassoc below_BAR
%nonassoc BAR

%start <Ast.expr> program

%%

program:
  | e = seq_expr; EOF { e }

seq_expr:
  | e = expr                          { e } %prec below_SEMI
  | e1 = expr; SEMI; e2 = seq_expr   { ESeq (e1, e2) }

expr:
  | LET; x = IDENT; EQ; e1 = seq_expr; IN; e2 = seq_expr
      { ELet (x, e1, e2) }
  | LET; REC; f = IDENT; x = IDENT; EQ; e1 = seq_expr; IN; e2 = seq_expr
      { ELetRec (f, x, e1, e2) }
  | IF; c = seq_expr; THEN; t = seq_expr; ELSE; e = seq_expr
      { EIf (c, t, e) }
  | FUN; x = IDENT; ARROW; e = seq_expr
      { EFun (x, e) }
  | MATCH; e = seq_expr; WITH; bs = match_cases
      { EMatch (e, bs) } %prec below_BAR
  | e = or_expr
      { e }

or_expr:
  | e = and_expr                            { e }
  | e1 = or_expr; BARBAR; e2 = and_expr    { EBinOp (Or, e1, e2) }

and_expr:
  | e = comp_expr                            { e }
  | e1 = and_expr; AMPAMP; e2 = comp_expr   { EBinOp (And, e1, e2) }

comp_expr:
  | e = cons_expr                                  { e }
  | e1 = cons_expr; op = comp_op; e2 = cons_expr  { EBinOp (op, e1, e2) }

%inline comp_op:
  | EQ  { Eq }
  | NEQ { Neq }
  | LT  { Lt }
  | GT  { Gt }
  | LE  { Le }
  | GE  { Ge }

cons_expr:
  | e = add_expr                                  { e }
  | e1 = add_expr; COLONCOLON; e2 = cons_expr    { ECons (e1, e2) }

add_expr:
  | e = mul_expr                              { e }
  | e1 = add_expr; PLUS; e2 = mul_expr       { EBinOp (Add, e1, e2) }
  | e1 = add_expr; MINUS; e2 = mul_expr      { EBinOp (Sub, e1, e2) }

mul_expr:
  | e = unary_expr                             { e }
  | e1 = mul_expr; TIMES; e2 = unary_expr     { EBinOp (Mul, e1, e2) }
  | e1 = mul_expr; DIV; e2 = unary_expr       { EBinOp (Div, e1, e2) }

unary_expr:
  | e = app_expr              { e }
  | MINUS; e = unary_expr     { EUnOp (Neg, e) }
  | NOT; e = unary_expr       { EUnOp (Not, e) }

app_expr:
  | e = simple_expr                         { e }
  | e1 = app_expr; e2 = simple_expr        { EApp (e1, e2) }

simple_expr:
  | i = INT
      { EInt i }
  | TRUE
      { EBool true }
  | FALSE
      { EBool false }
  | x = IDENT
      { EVar x }
  | LPAREN; e = seq_expr; RPAREN
      { e }
  | LPAREN; e = expr; COMMA; es = separated_nonempty_list(COMMA, expr); RPAREN
      { ETuple (e :: es) }
  | LBRACKET; es = separated_list(SEMI, expr); RBRACKET
      { EList es }

match_cases:
  | option(BAR); p = pattern; ARROW; e = seq_expr
      { [(p, e)] }
  | cs = match_cases; BAR; p = pattern; ARROW; e = seq_expr
      { cs @ [(p, e)] }

pattern:
  | p1 = simple_pattern; COLONCOLON; p2 = pattern   { PCons (p1, p2) }
  | p = simple_pattern                               { p }

simple_pattern:
  | UNDERSCORE  { PWild }
  | x = IDENT   { PVar x }
  | i = INT     { PInt i }
  | TRUE        { PBool true }
  | FALSE       { PBool false }
  | LPAREN; p = pattern; COMMA; ps = separated_nonempty_list(COMMA, pattern); RPAREN
      { PTuple (p :: ps) }
  | LBRACKET; ps = separated_list(SEMI, pattern); RBRACKET
      { PList ps }

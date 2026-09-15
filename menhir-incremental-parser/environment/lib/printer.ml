open Ast

let binop_str = function
  | Add -> "+" | Sub -> "-" | Mul -> "*" | Div -> "/"
  | Eq -> "=" | Neq -> "<>" | Lt -> "<" | Gt -> ">"
  | Le -> "<=" | Ge -> ">="
  | And -> "&&" | Or -> "||"

let unop_str = function
  | Neg -> "-" | Not -> "not"

let spaced f = function
  | [] -> ""
  | xs -> " " ^ String.concat " " (List.map f xs)

let rec print_expr = function
  | EInt n -> string_of_int n
  | EBool b -> string_of_bool b
  | EVar x -> x
  | EBinOp (op, e1, e2) ->
    Printf.sprintf "(%s %s %s)" (binop_str op) (print_expr e1) (print_expr e2)
  | EUnOp (op, e) ->
    Printf.sprintf "(%s %s)" (unop_str op) (print_expr e)
  | ELet (x, e1, e2) ->
    Printf.sprintf "(let %s %s %s)" x (print_expr e1) (print_expr e2)
  | ELetRec (f, x, e1, e2) ->
    Printf.sprintf "(letrec %s %s %s %s)" f x (print_expr e1) (print_expr e2)
  | EIf (e1, e2, e3) ->
    Printf.sprintf "(if %s %s %s)" (print_expr e1) (print_expr e2) (print_expr e3)
  | EFun (x, e) ->
    Printf.sprintf "(fun %s %s)" x (print_expr e)
  | EApp (e1, e2) ->
    Printf.sprintf "(app %s %s)" (print_expr e1) (print_expr e2)
  | ETuple es ->
    Printf.sprintf "(tuple%s)" (spaced print_expr es)
  | EList es ->
    Printf.sprintf "(list%s)" (spaced print_expr es)
  | ECons (e1, e2) ->
    Printf.sprintf "(:: %s %s)" (print_expr e1) (print_expr e2)
  | EMatch (e, branches) ->
    Printf.sprintf "(match %s%s)" (print_expr e) (spaced print_branch branches)
  | ESeq (e1, e2) ->
    Printf.sprintf "(seq %s %s)" (print_expr e1) (print_expr e2)

and print_branch (p, e) =
  Printf.sprintf "(-> %s %s)" (print_pattern p) (print_expr e)

and print_pattern = function
  | PWild -> "_"
  | PVar x -> x
  | PInt n -> string_of_int n
  | PBool b -> string_of_bool b
  | PTuple ps ->
    Printf.sprintf "(tuple%s)" (spaced print_pattern ps)
  | PList ps ->
    Printf.sprintf "(list%s)" (spaced print_pattern ps)
  | PCons (p1, p2) ->
    Printf.sprintf "(:: %s %s)" (print_pattern p1) (print_pattern p2)

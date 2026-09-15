type binop =
  | Add | Sub | Mul | Div
  | Eq | Neq | Lt | Gt | Le | Ge
  | And | Or

type unop = Neg | Not

type expr =
  | EInt of int
  | EBool of bool
  | EVar of string
  | EBinOp of binop * expr * expr
  | EUnOp of unop * expr
  | ELet of string * expr * expr
  | ELetRec of string * string * expr * expr
  | EIf of expr * expr * expr
  | EFun of string * expr
  | EApp of expr * expr
  | ETuple of expr list
  | EList of expr list
  | ECons of expr * expr
  | EMatch of expr * branch list
  | ESeq of expr * expr

and branch = pattern * expr

and pattern =
  | PWild
  | PVar of string
  | PInt of int
  | PBool of bool
  | PTuple of pattern list
  | PList of pattern list
  | PCons of pattern * pattern

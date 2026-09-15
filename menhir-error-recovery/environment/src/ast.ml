type binop =
  | Add | Sub | Mul | Div
  | Eq | Ne | Lt | Le | Gt | Ge
  | And | Or

type expr =
  | Int of int
  | Bool of bool
  | Var of string
  | BinOp of binop * expr * expr
  | UnaryMinus of expr
  | Let of string * expr * expr
  | If of expr * expr * expr
  | Fun of string * expr
  | App of expr * expr
  | Seq of expr * expr

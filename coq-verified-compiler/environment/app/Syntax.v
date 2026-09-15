(* Syntax.v - Expression language AST for a verified compiler.
   This file defines the source language: arithmetic expressions
   over natural numbers with addition, subtraction, and multiplication. *)

Inductive expr : Type :=
  | Const : nat -> expr
  | Plus  : expr -> expr -> expr
  | Minus : expr -> expr -> expr
  | Times : expr -> expr -> expr.

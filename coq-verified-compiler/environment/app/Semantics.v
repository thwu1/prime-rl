(* Semantics.v - Denotational semantics for the expression language.
   Evaluation maps expressions to natural numbers.
   Subtraction is truncated at zero (Coq nat). *)

Require Import Arith.
Require Import Syntax.

Fixpoint eval (e : expr) : nat :=
  match e with
  | Const n => n
  | Plus e1 e2 => eval e1 + eval e2
  | Minus e1 e2 => eval e1 - eval e2
  | Times e1 e2 => eval e1 * eval e2
  end.

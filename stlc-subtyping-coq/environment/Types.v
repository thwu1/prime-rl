(* Types.v - Type syntax for STLC with subtyping *)

Require Export String.

Inductive ty : Type :=
  | Ty_Top   : ty
  | Ty_Arrow : ty -> ty -> ty
  | Ty_Prod  : ty -> ty -> ty
  | Ty_Unit  : ty.

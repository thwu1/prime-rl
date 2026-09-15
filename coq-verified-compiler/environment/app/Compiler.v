(* Compiler.v - Compiler from expressions to stack machine code.
   The compiler emits instructions in left-to-right order:
   first compile the left operand, then the right, then the operator. *)

Require Import List Arith.
Require Import Syntax Semantics StackMachine.
Import ListNotations.

Fixpoint compile (e : expr) : list instr :=
  match e with
  | Const n     => [IPush n]
  | Plus e1 e2  => compile e1 ++ compile e2 ++ [IAdd]
  | Minus e1 e2 => compile e1 ++ compile e2 ++ [ISub]
  | Times e1 e2 => compile e1 ++ compile e2 ++ [IMul]
  end.

(* The fundamental correctness theorem: executing compiled code
   pushes exactly the evaluated result onto the stack. *)
Theorem compile_correct : forall e s,
  exec (compile e) s = Some (eval e :: s).
Proof.
Admitted.

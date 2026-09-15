(* Compiler.v - with completed compile_correct proof *)

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

Theorem compile_correct : forall e s,
  exec (compile e) s = Some (eval e :: s).
Proof.
  induction e; intros s; simpl.
  - reflexivity.
  - rewrite exec_app. rewrite IHe1.
    rewrite exec_app. rewrite IHe2.
    simpl. reflexivity.
  - rewrite exec_app. rewrite IHe1.
    rewrite exec_app. rewrite IHe2.
    simpl. reflexivity.
  - rewrite exec_app. rewrite IHe1.
    rewrite exec_app. rewrite IHe2.
    simpl. reflexivity.
Qed.

(* Optimizer.v - FIXED: Minus folds with subtraction, proof completed *)

Require Import Arith.
Require Import Syntax Semantics.

Fixpoint optimize (e : expr) : expr :=
  match e with
  | Const n => Const n
  | Plus e1 e2 =>
      match optimize e1, optimize e2 with
      | Const n1, Const n2 => Const (n1 + n2)
      | e1', e2' => Plus e1' e2'
      end
  | Minus e1 e2 =>
      match optimize e1, optimize e2 with
      | Const n1, Const n2 => Const (n1 - n2)
      | e1', e2' => Minus e1' e2'
      end
  | Times e1 e2 =>
      match optimize e1, optimize e2 with
      | Const n1, Const n2 => Const (n1 * n2)
      | e1', e2' => Times e1' e2'
      end
  end.

Theorem optimize_correct : forall e,
  eval (optimize e) = eval e.
Proof.
  induction e; simpl; auto;
    destruct (optimize e1); destruct (optimize e2);
    simpl in *; congruence.
Qed.

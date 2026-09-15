(* StackMachine.v - FIXED: ISub now correctly computes b - a *)

Require Import List Arith Lia.
Require Import Syntax.
Import ListNotations.

Inductive instr : Type :=
  | IPush : nat -> instr
  | IAdd  : instr
  | ISub  : instr
  | IMul  : instr.

Definition stack := list nat.

Fixpoint exec (prog : list instr) (s : stack) : option stack :=
  match prog with
  | []             => Some s
  | IPush n :: rest => exec rest (n :: s)
  | IAdd :: rest =>
      match s with
      | a :: b :: s' => exec rest ((b + a) :: s')
      | _ => None
      end
  | ISub :: rest =>
      match s with
      | a :: b :: s' => exec rest ((b - a) :: s')
      | _ => None
      end
  | IMul :: rest =>
      match s with
      | a :: b :: s' => exec rest ((b * a) :: s')
      | _ => None
      end
  end.

Lemma exec_app : forall p1 p2 s,
  exec (p1 ++ p2) s = match exec p1 s with
                       | Some s' => exec p2 s'
                       | None => None
                       end.
Proof.
  induction p1 as [| i p1' IH]; intros p2 s.
  - simpl. reflexivity.
  - destruct i; simpl.
    + apply IH.
    + destruct s as [| a [| b s']]; try reflexivity. apply IH.
    + destruct s as [| a [| b s']]; try reflexivity. apply IH.
    + destruct s as [| a [| b s']]; try reflexivity. apply IH.
Qed.

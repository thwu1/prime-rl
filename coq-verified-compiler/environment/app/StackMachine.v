(* StackMachine.v - A simple stack machine for arithmetic.
   Instructions push constants or perform binary operations
   on the top two stack elements. *)

Require Import List Arith Lia.
Require Import Syntax.
Import ListNotations.

Inductive instr : Type :=
  | IPush : nat -> instr
  | IAdd  : instr
  | ISub  : instr
  | IMul  : instr.

Definition stack := list nat.

(* Execute a program on a stack. For binary operations, the
   top of the stack is the SECOND operand (pushed last).
   E.g., to compute e1 - e2: push e1, push e2, ISub.
   Stack before ISub: [e2_val; e1_val; ...]
   a = e2_val (top), b = e1_val (second)
   Result should be e1_val - e2_val = b - a. *)
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
      | a :: b :: s' => exec rest ((a - b) :: s')
      | _ => None
      end
  | IMul :: rest =>
      match s with
      | a :: b :: s' => exec rest ((b * a) :: s')
      | _ => None
      end
  end.

(* Key lemma: executing concatenated programs is compositional. *)
Lemma exec_app : forall p1 p2 s,
  exec (p1 ++ p2) s = match exec p1 s with
                       | Some s' => exec p2 s'
                       | None => None
                       end.
Proof.
Admitted.

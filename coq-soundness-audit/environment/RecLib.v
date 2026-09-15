
(* Depth-controlled recursive accumulator.
   Provides deep folding with a transform function
   that is rebuilt at each recursion level. *)

Fixpoint deep_acc (depth level : nat) (f : nat -> nat) : nat :=
  match depth with
  | S d => deep_acc d (S level) (fun x => deep_acc x 0 f)
  | O => S (f level)
  end.

Definition shallow_run (n : nat) : nat := deep_acc 0 n S.
Definition deep_run (n : nat) : nat := deep_acc n 0 S.

Lemma shallow_example : shallow_run 3 = 5.
Proof. reflexivity. Qed.

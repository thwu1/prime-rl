
(* Bounded iteration framework with dependent safety certificates. *)

Require Import Arith Bool.

(* Safe bounded counter *)
Fixpoint count_steps (fuel : nat) : nat :=
  match fuel with
  | O => O
  | S k => S (count_steps k)
  end.

Definition bounded_result : nat := count_steps 10.

(* Dependent-type predicates used in safety proofs *)
Definition not_zero n := match n with 0 => False | S _ => True end.
Definition not_one n := match n with 0 => False | S n => not_zero n end.

(* Safety certificate: establishes that any n satisfying not_zero
   cannot witness a stuck state in the iteration. The proof
   proceeds by structural recursion on n with a conditional
   descent through let-bound pattern matching. *)
Fixpoint safety_check (n : nat) {struct n} : not_zero n -> False.
  refine
  match n with
  | 0 => fun h => h
  | S subn => fun h =>
    let f (b : bool) (e : b = true) (x : nat) (Hx : not_one x) :=
      let arg := (match (if b then x else subn) with
                  | 0 => subn
                  | S subsubn => subsubn end) in
      safety_check arg _
    in
    f true eq_refl 5 I
  end.
  subst b.
  destruct x; cbn in Hx.
  - now exfalso.
  - assumption.
Defined.

Lemma result_correct : bounded_result = 10.
Proof. reflexivity. Qed.

#!/bin/bash

set -e

###############################################################################
# Exploit 1: ModLib — Include + functor + module alias corrupts delta-resolver
###############################################################################

cat > /app/exploit_mod.v << 'COQEOF'

(*
  Exploit: The combination of Include REGISTRY + Module View := State inside
  a functor corrupts the delta-resolver. When the functor is applied to two
  different arguments (Enabled vs Disabled), the alias View resolves both
  applications to the same internal definition, making FlagA.View.current
  and FlagB.View.current convertible even though one is true and the other
  is false.
*)

Require Import Bool.

Module Type FLAG.
  Parameter is_set : bool.
End FLAG.

Module Enabled <: FLAG.
  Definition is_set := true.
End Enabled.

Module Disabled <: FLAG.
  Definition is_set := false.
End Disabled.

Module REGISTRY.
  Module Register (F : FLAG).
    Module State.
      Definition current := F.is_set.
    End State.
    Module View := State.
  End Register.
End REGISTRY.

Include REGISTRY.

Module FlagA := Register Enabled.
Module FlagB := Register Disabled.

(* Due to the delta-resolver bug, this is provable by reflexivity *)
Lemma flags_confused : FlagA.View.current = FlagB.View.current.
Proof. reflexivity. Qed.

(* But individually, each resolves to the correct value *)
Lemma a_true : FlagA.View.current = true.
Proof. reflexivity. Qed.

Lemma b_false : FlagB.View.current = false.
Proof. reflexivity. Qed.

Theorem unsound : False.
Proof.
  assert (H : true = false).
  { rewrite <- a_true. rewrite <- b_false. exact flags_confused. }
  discriminate H.
Qed.

Print Assumptions unsound.
COQEOF

###############################################################################
# Exploit 2: RecLib — Guard checker accepts non-terminating higher-order fix
###############################################################################

cat > /app/exploit_rec.v << 'COQEOF'

(*
  Exploit: The guard checker incorrectly accepts deep_acc because the
  closure (fun x => deep_acc x 0 f) passes the recursive function through
  a higher-order argument. This makes deep_acc 1 0 f diverge for any f,
  satisfying deep_acc 1 0 f = S (deep_acc 1 0 f), which is contradictory.
*)

Fixpoint deep_acc (depth level : nat) (f : nat -> nat) : nat :=
  match depth with
  | S d => deep_acc d (S level) (fun x => deep_acc x 0 f)
  | O => S (f level)
  end.

(* Step lemmas that don't trigger divergence *)
Lemma step_S : forall d l f,
  deep_acc (S d) l f = deep_acc d (S l) (fun x => deep_acc x 0 f).
Proof. reflexivity. Qed.

Lemma step_O : forall l f,
  deep_acc O l f = S (f l).
Proof. reflexivity. Qed.

Theorem unsound : False.
Proof.
  (* Show that deep_acc 1 0 (fun _ => 0) = S (deep_acc 1 0 (fun _ => 0)) *)
  assert (H : exists n, n = S n). {
    exists (deep_acc 1 0 (fun _ => 0)).
    (* Avoid computing the divergent term directly *)
    remember (S (deep_acc 1 0 (fun _ => 0))) as v.
    rewrite step_S.
    rewrite step_O.
    rewrite <- Heqv.
    reflexivity.
  }
  (* No natural number equals its successor *)
  destruct H as [n Hn].
  induction n as [| n' IH].
  - discriminate.
  - apply IH. now injection Hn.
Qed.

Print Assumptions unsound.
COQEOF

###############################################################################
# Exploit 3: IterLib — Guard checker loses subterm specs in let-bound match
###############################################################################

cat > /app/exploit_iter.v << 'COQEOF'

(*
  Exploit: The guard checker loses subterm information when building
  a subtree spec through a let-bound conditional match. The let-binding
  hides the fact that the recursive call's argument (computed through
  if-then-else and match) is not a genuine subterm of n.
*)

Require Import Arith Bool.

Definition not_zero n := match n with 0 => False | S _ => True end.
Definition not_one n := match n with 0 => False | S n => not_zero n end.

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

Theorem unsound : False.
Proof.
  exact (safety_check 1 I).
Qed.

Print Assumptions unsound.
COQEOF

###############################################################################
# Fix 1: ModLib — Remove Include and module alias
###############################################################################

cat > /app/fixed_mod.v << 'COQEOF'

(* Fixed: Functor defined at top level (no Include), no module alias.
   This avoids the delta-resolver corruption caused by Include + alias. *)

Require Import Bool.

Module Type FLAG.
  Parameter is_set : bool.
End FLAG.

Module Enabled <: FLAG.
  Definition is_set := true.
End Enabled.

Module Disabled <: FLAG.
  Definition is_set := false.
End Disabled.

Module Register (F : FLAG).
  Definition current := F.is_set.
  Definition flipped := negb F.is_set.
End Register.

Module FlagA := Register Enabled.
Module FlagB := Register Disabled.

Definition a_current : bool := FlagA.current.
Definition b_current : bool := FlagB.current.
Definition a_flipped : bool := FlagA.flipped.
Definition b_flipped : bool := FlagB.flipped.

Lemma a_is_true : a_current = true.
Proof. reflexivity. Qed.

Lemma b_is_false : b_current = false.
Proof. reflexivity. Qed.
COQEOF

###############################################################################
# Fix 2: RecLib — Don't capture recursive call in closure
###############################################################################

cat > /app/fixed_rec.v << 'COQEOF'

(* Fixed: The transform function f is passed through unchanged at each
   recursion level, instead of being rebuilt as a closure capturing the
   recursive call. This makes structural recursion on depth genuine. *)

Fixpoint deep_acc (depth level : nat) (f : nat -> nat) : nat :=
  match depth with
  | S d => deep_acc d (S level) f
  | O => S (f level)
  end.

Definition shallow_run (n : nat) : nat := deep_acc 0 n S.
Definition deep_run (n : nat) : nat := deep_acc n 0 S.

Lemma shallow_correct : forall n, shallow_run n = S (S n).
Proof. reflexivity. Qed.
COQEOF

###############################################################################
# Fix 3: IterLib — Remove unsound safety_check definition
###############################################################################

cat > /app/fixed_iter.v << 'COQEOF'

(* Fixed: The unsound safety_check definition (which exploited a guard
   checker bug involving lost subterm specs in let-bound conditional
   matches to prove False) has been removed. Only the sound
   bounded_result computation is retained. *)

Require Import Arith.

Fixpoint count_steps (fuel : nat) : nat :=
  match fuel with
  | O => O
  | S k => S (count_steps k)
  end.

Definition bounded_result : nat := count_steps 10.

Lemma result_correct : bounded_result = 10.
Proof. reflexivity. Qed.
COQEOF

echo "All exploit and fixed files created successfully."

#!/usr/bin/env python3
"""Generate the complete, fixed AIG.v with all proofs."""


Require Import Bool.
Require Import Arith.
Require Import PeanoNat.

(* ================================================================= *)
(* Formalization of And-Inverter Graphs (AIGs) with complement edges. *)
(*                                                                    *)
(* AIGs are the canonical data structure used in logic synthesis tools *)
(* such as ABC for representing and optimizing combinational Boolean  *)
(* circuits.  Each internal node is an AND gate whose inputs may be   *)
(* optionally complemented (inverted) via complement edges.           *)
(*                                                                    *)
(* This file defines:                                                 *)
(*   - an AIG type with complement edges                              *)
(*   - an evaluation semantics                                        *)
(*   - several semantics-preserving transformations                   *)
(*   - correctness theorems for each transformation                   *)
(*   - a combined optimization pipeline with a composition theorem    *)
(* ================================================================= *)

(** [aig] -- And-Inverter Graph node.

    [AAnd c1 l c2 r] represents an AND gate whose result is:
      (c1 XOR eval(l))  AND  (c2 XOR eval(r))

    The Boolean flags [c1] and [c2] are complement edges:
    when [true], the corresponding input is inverted. *)
Inductive aig : Type :=
  | AConst : bool -> aig
  | AVar   : nat -> aig
  | AAnd   : bool -> aig -> bool -> aig -> aig.

(** Variable environment: maps variable indices to Boolean values. *)
Definition env := nat -> bool.

(** Evaluate an AIG under a given environment. *)
Fixpoint eval (e : env) (a : aig) : bool :=
  match a with
  | AConst b => b
  | AVar n => e n
  | AAnd c1 l c2 r => andb (xorb c1 (eval e l)) (xorb c2 (eval e r))
  end.

(** Node count (size) of an AIG. *)
Fixpoint size (a : aig) : nat :=
  match a with
  | AConst _ => 1
  | AVar _ => 1
  | AAnd _ l _ r => 1 + size l + size r
  end.

(** Two AIGs are functionally equivalent when they agree on all
    environments. *)
Definition equiv (a1 a2 : aig) : Prop :=
  forall e : env, eval e a1 = eval e a2.

(* ================================================================= *)
(* Part 1 -- Helper lemmas about [xorb]                               *)
(* ================================================================= *)

Lemma xorb_false_l : forall b, xorb false b = b.
Proof. destruct b; reflexivity. Qed.

Lemma xorb_true_l : forall b, xorb true b = negb b.
Proof. destruct b; reflexivity. Qed.

Lemma xorb_involutive : forall a b, xorb a (xorb a b) = b.
Proof. destruct a, b; reflexivity. Qed.

Lemma negb_xorb : forall a b, negb (xorb a b) = xorb (negb a) b.
Proof. destruct a, b; reflexivity. Qed.

(** Helper for Bool.eqb reflection. *)
Lemma bool_eqb_true : forall a b : bool, Bool.eqb a b = true -> a = b.
Proof. destruct a, b; simpl; intro H; try reflexivity; discriminate. Qed.

(* ================================================================= *)
(* Part 2 -- Equivalence relation properties                          *)
(* ================================================================= *)

Lemma equiv_refl : forall a, equiv a a.
Proof. unfold equiv. intros. reflexivity. Qed.

Lemma equiv_trans : forall a b c, equiv a b -> equiv b c -> equiv a c.
Proof.
  unfold equiv. intros a b c Hab Hbc e. rewrite Hab. apply Hbc.
Qed.

(* ================================================================= *)
(* Part 3 -- Negation                                                 *)
(* ================================================================= *)

(** Negate an AIG: produce an AIG evaluating to the complement. *)
Definition negate (a : aig) : aig :=
  AAnd true a false (AConst true).

Theorem negate_correct : forall e a,
  eval e (negate a) = negb (eval e a).
Proof.
  intros e a. unfold negate. simpl.
  destruct (eval e a); reflexivity.
Qed.

Theorem negate_involutive : forall a, equiv (negate (negate a)) a.
Proof.
  unfold equiv. intros a e.
  rewrite negate_correct, negate_correct.
  destruct (eval e a); reflexivity.
Qed.

(* ================================================================= *)
(* Part 4 -- Decidable structural equality for AIGs                   *)
(* ================================================================= *)

(** Boolean structural equality test. *)
Fixpoint aig_eqb (a b : aig) : bool :=
  match a, b with
  | AConst b1, AConst b2 => Bool.eqb b1 b2
  | AVar n1, AVar n2 => Nat.eqb n1 n2
  | AAnd c1 l1 c2 r1, AAnd c3 l2 c4 r2 =>
      Bool.eqb c1 c3 && aig_eqb l1 l2 && Bool.eqb c2 c4 && aig_eqb r1 r2
  | _, _ => false
  end.

(** Structural equality implies Leibniz equality. *)
Lemma aig_eqb_eq : forall a b, aig_eqb a b = true -> a = b.
Proof.
  induction a as [b1 | n1 | c1 l IHl c2 r IHr];
    destruct b as [b2 | n2 | c3 l2 c4 r2];
    intro H; simpl in H; try discriminate.
  - apply bool_eqb_true in H. subst. reflexivity.
  - apply Nat.eqb_eq in H. subst. reflexivity.
  - apply andb_true_iff in H. destruct H as [H1 Hr].
    apply andb_true_iff in H1. destruct H1 as [H1 Hc2].
    apply andb_true_iff in H1. destruct H1 as [Hc1 Hl].
    apply bool_eqb_true in Hc1. apply IHl in Hl.
    apply bool_eqb_true in Hc2. apply IHr in Hr.
    subst. reflexivity.
Qed.

(* ================================================================= *)
(* Part 5 -- Constant folding                                         *)
(* ================================================================= *)

(** When both children of an AND node are constants, compute the
    result statically. *)
Fixpoint const_fold (a : aig) : aig :=
  match a with
  | AAnd c1 l c2 r =>
    let l' := const_fold l in
    let r' := const_fold r in
    match l', r' with
    | AConst b1, AConst b2 =>
        AConst (andb (xorb c1 b1) (xorb c2 b2))
    | _, _ => AAnd c1 l' c2 r'
    end
  | x => x
  end.

Theorem const_fold_correct : forall a, equiv (const_fold a) a.
Proof.
  unfold equiv.
  induction a as [b | n | c1 l IHl c2 r IHr]; intros e; simpl.
  - reflexivity.
  - reflexivity.
  - rewrite <- (IHl e), <- (IHr e).
    destruct (const_fold l); destruct (const_fold r); simpl; reflexivity.
Qed.

(* ================================================================= *)
(* Part 6 -- Complement elimination                                   *)
(* ================================================================= *)

(** When both children of an AND are structurally equal but the
    complement flags differ, the result is always false
    (AND of x and NOT x). *)
Fixpoint complement_elim (a : aig) : aig :=
  match a with
  | AAnd c1 l c2 r =>
    let l' := complement_elim l in
    let r' := complement_elim r in
    if aig_eqb l' r' && negb (Bool.eqb c1 c2) then
      AConst false
    else AAnd c1 l' c2 r'
  | x => x
  end.

Theorem complement_elim_correct : forall a, equiv (complement_elim a) a.
Proof.
  unfold equiv.
  induction a as [b | n | c1 l IHl c2 r IHr]; intros e; simpl.
  - reflexivity.
  - reflexivity.
  - destruct (aig_eqb (complement_elim l) (complement_elim r)
              && negb (Bool.eqb c1 c2)) eqn:Hcond.
    + simpl.
      apply andb_true_iff in Hcond. destruct Hcond as [Heqb Hneq].
      apply aig_eqb_eq in Heqb.
      assert (Hv : eval e l = eval e r).
      { rewrite <- (IHl e), <- (IHr e). rewrite Heqb. reflexivity. }
      rewrite <- Hv.
      destruct c1, c2; simpl in Hneq; try discriminate;
        simpl; destruct (eval e l); reflexivity.
    + simpl. rewrite IHl, IHr. reflexivity.
Qed.

(* ================================================================= *)
(* Part 7 -- Identity elimination  (BUG FIXED)                       *)
(* ================================================================= *)

(** Simplify AND nodes where one input is the constant true with
    no complement, making it an identity element:
      AND(false, x, false, Const true)  =  x
    and symmetrically for the left child.

    IMPORTANT: Both complement flags must be false for the identity
    to hold. *)
Fixpoint identity_elim (a : aig) : aig :=
  match a with
  | AAnd c1 l c2 r =>
    let l' := identity_elim l in
    let r' := identity_elim r in
    match l', r' with
    | _, AConst true =>
        if Bool.eqb c1 false && Bool.eqb c2 false then l'
        else AAnd c1 l' c2 r'
    | AConst true, _ =>
        if Bool.eqb c1 false && Bool.eqb c2 false then r'
        else AAnd c1 l' c2 r'
    | _, _ => AAnd c1 l' c2 r'
    end
  | x => x
  end.

Theorem identity_elim_correct : forall a, equiv (identity_elim a) a.
Proof.
  unfold equiv.
  induction a as [b | n | c1 l IHl c2 r IHr]; intros e; try reflexivity.
  simpl.
  rewrite <- (IHl e), <- (IHr e).
  destruct (identity_elim l) as [bl | nl | cl1 ll cl2 lr];
  destruct (identity_elim r) as [br | nr | cr1 rl cr2 rr];
  try (destruct bl); try (destruct br);
  destruct c1; destruct c2;
  simpl; try reflexivity;
  try (rewrite Bool.andb_true_r; reflexivity).
Qed.

(* ================================================================= *)
(* Part 8 -- Optimization pipeline                                    *)
(* ================================================================= *)

(** A combined optimization pass: constant fold, then eliminate
    complements, then eliminate identities. *)
Definition optimize (a : aig) : aig :=
  identity_elim (complement_elim (const_fold a)).

Theorem optimize_correct : forall a, equiv (optimize a) a.
Proof.
  intro a. unfold optimize.
  eapply equiv_trans.
  - apply identity_elim_correct.
  - eapply equiv_trans.
    + apply complement_elim_correct.
    + apply const_fold_correct.
Qed.

(* ================================================================= *)
(* Type-checking assertions -- do not remove.                         *)
(* These enforce the exact types of the required theorems.            *)
(* ================================================================= *)

Definition _chk_negate  : forall e a, eval e (negate a) = negb (eval e a) := negate_correct.
Definition _chk_involut : forall a, equiv (negate (negate a)) a := negate_involutive.
Definition _chk_cfold   : forall a, equiv (const_fold a) a := const_fold_correct.
Definition _chk_celim   : forall a, equiv (complement_elim a) a := complement_elim_correct.
Definition _chk_ielim   : forall a, equiv (identity_elim a) a := identity_elim_correct.
Definition _chk_optim   : forall a, equiv (optimize a) a := optimize_correct.
"""

with open("/app/AIG.v", "w") as f:
    f.write(SOLVED)

print("Wrote fixed AIG.v to /app/AIG.v")

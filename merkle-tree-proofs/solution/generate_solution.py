#!/usr/bin/env python3

"""Generate the complete MerkleTree.v with all proofs filled in."""


SOLUTION = r'''(* MerkleTree.v — Formalization of Merkle hash trees with
   cryptographic security properties. *)

Require Import Arith.
Require Import Bool.
Require Import List.
Require Import PeanoNat.
Require Import Lia.
Import ListNotations.

(* ================================================================ *)
(* Collision-Resistant Hash Function (axiomatized)                   *)
(* We model collision resistance in the ideal (random oracle) model  *)
(* by assuming the hash function is injective.                       *)
(* ================================================================ *)

Parameter hash : nat -> nat -> nat.

Axiom hash_inj : forall a b c d,
  hash a b = hash c d -> a = c /\ b = d.

(* ================================================================ *)
(* Merkle Tree Structure                                             *)
(* ================================================================ *)

Inductive tree : Type :=
| Leaf : nat -> tree
| Node : tree -> tree -> tree.

(* Root hash of the tree *)
Fixpoint root (t : tree) : nat :=
  match t with
  | Leaf v => v
  | Node l r => hash (root l) (root r)
  end.

(* Number of leaves *)
Fixpoint num_leaves (t : tree) : nat :=
  match t with
  | Leaf _ => 1
  | Node l r => num_leaves l + num_leaves r
  end.

(* Depth of the i-th leaf (0-indexed, left-to-right) *)
Fixpoint leaf_depth (t : tree) (i : nat) : option nat :=
  match t with
  | Leaf _ => if i =? 0 then Some 0 else None
  | Node l r =>
    if i <? num_leaves l then
      match leaf_depth l i with
      | Some d => Some (S d)
      | None => None
      end
    else
      match leaf_depth r (i - num_leaves l) with
      | Some d => Some (S d)
      | None => None
      end
  end.

(* ================================================================ *)
(* Authentication Paths                                              *)
(* ================================================================ *)

Inductive dir : Type := GoLeft | GoRight.

Definition auth_path := list (dir * nat).

Fixpoint reconstruct (v : nat) (p : auth_path) : nat :=
  match p with
  | nil => v
  | (GoLeft, s) :: rest => reconstruct (hash s v) rest
  | (GoRight, s) :: rest => reconstruct (hash v s) rest
  end.

Definition verify (v : nat) (p : auth_path) (expected_root : nat) : bool :=
  (reconstruct v p) =? expected_root.

(* ================================================================ *)
(* Proof Generation and Leaf Access                                  *)
(* ================================================================ *)

Fixpoint get_leaf (t : tree) (i : nat) : option nat :=
  match t with
  | Leaf v => if i =? 0 then Some v else None
  | Node l r =>
    if i <? num_leaves l then get_leaf l i
    else get_leaf r (i - num_leaves l)
  end.

Fixpoint gen_proof (t : tree) (i : nat) : option (nat * auth_path) :=
  match t with
  | Leaf v => if i =? 0 then Some (v, nil) else None
  | Node l r =>
    if i <? num_leaves l then
      match gen_proof l i with
      | Some (v, p) => Some (v, p ++ [(GoRight, root r)])
      | None => None
      end
    else
      match gen_proof r (i - num_leaves l) with
      | Some (v, p) => Some (v, p ++ [(GoLeft, root l)])
      | None => None
      end
  end.

Fixpoint set_leaf (t : tree) (i : nat) (new_val : nat) : tree :=
  match t with
  | Leaf _ => Leaf new_val
  | Node l r =>
    if i <? num_leaves l then Node (set_leaf l i new_val) r
    else Node l (set_leaf r (i - num_leaves l) new_val)
  end.

(* ================================================================ *)
(* Helper Lemmas                                                     *)
(* ================================================================ *)

(* Appending a GoRight step to the path corresponds to hashing
   the accumulated value on the left with the sibling on the right. *)
Lemma reconstruct_app_GoRight : forall p v s,
  reconstruct v (p ++ [(GoRight, s)]) = hash (reconstruct v p) s.
Proof.
  induction p as [| [[|] x] rest IH]; intros; simpl.
  - reflexivity.
  - apply IH.
  - apply IH.
Qed.

(* Symmetric: appending a GoLeft step hashes sibling on left. *)
Lemma reconstruct_app_GoLeft : forall p v s,
  reconstruct v (p ++ [(GoLeft, s)]) = hash s (reconstruct v p).
Proof.
  induction p as [| [[|] x] rest IH]; intros; simpl.
  - reflexivity.
  - apply IH.
  - apply IH.
Qed.

(* reconstruct is injective in the leaf value for a fixed path,
   because hash is injective. *)
Lemma reconstruct_injective : forall p v1 v2,
  reconstruct v1 p = reconstruct v2 p -> v1 = v2.
Proof.
  induction p as [| [[|] s] rest IH]; simpl; intros ? ? Heq.
  - exact Heq.
  - apply IH in Heq. apply hash_inj in Heq.
    destruct Heq as [_ Hval]. exact Hval.
  - apply IH in Heq. apply hash_inj in Heq.
    destruct Heq as [Hval _]. exact Hval.
Qed.

(* ================================================================ *)
(* Main Theorems                                                     *)
(* ================================================================ *)

Theorem completeness : forall t i v p,
  gen_proof t i = Some (v, p) ->
  verify v p (root t) = true.
Proof.
  induction t as [val | l IHl r IHr];
    intros i v p Hgen; simpl in Hgen.
  - (* Leaf *)
    destruct (i =? 0) eqn:Hi; [| discriminate].
    inversion Hgen; subst.
    unfold verify; simpl. apply Nat.eqb_refl.
  - (* Node *)
    destruct (i <? num_leaves l) eqn:Hlt.
    + (* left subtree *)
      destruct (gen_proof l i) as [[v' p']|] eqn:Hgl; [| discriminate].
      inversion Hgen; subst.
      unfold verify. rewrite reconstruct_app_GoRight. simpl.
      specialize (IHl _ _ _ Hgl). unfold verify in IHl.
      apply Nat.eqb_eq in IHl. rewrite IHl.
      apply Nat.eqb_refl.
    + (* right subtree *)
      destruct (gen_proof r (i - num_leaves l)) as [[v' p']|] eqn:Hgr;
        [| discriminate].
      inversion Hgen; subst.
      unfold verify. rewrite reconstruct_app_GoLeft. simpl.
      specialize (IHr _ _ _ Hgr). unfold verify in IHr.
      apply Nat.eqb_eq in IHr. rewrite IHr.
      apply Nat.eqb_refl.
Qed.

Theorem binding : forall p v1 v2 r,
  verify v1 p r = true ->
  verify v2 p r = true ->
  v1 = v2.
Proof.
  unfold verify. intros p v1 v2 r H1 H2.
  apply Nat.eqb_eq in H1. apply Nat.eqb_eq in H2.
  apply (reconstruct_injective p). congruence.
Qed.

Theorem gen_proof_extracts_leaf : forall t i v p,
  gen_proof t i = Some (v, p) ->
  get_leaf t i = Some v.
Proof.
  induction t as [val | l IHl r IHr];
    intros i v p Hgen; simpl in *.
  - destruct (i =? 0) eqn:Hi; [| discriminate].
    inversion Hgen; subst. reflexivity.
  - destruct (i <? num_leaves l) eqn:Hlt.
    + destruct (gen_proof l i) as [[v' p']|] eqn:Hgl; [| discriminate].
      inversion Hgen; subst.
      exact (IHl _ _ _ Hgl).
    + destruct (gen_proof r (i - num_leaves l)) as [[v' p']|] eqn:Hgr;
        [| discriminate].
      inversion Hgen; subst.
      exact (IHr _ _ _ Hgr).
Qed.

Theorem update_soundness : forall t i old_val old_path new_val,
  gen_proof t i = Some (old_val, old_path) ->
  verify new_val old_path (root (set_leaf t i new_val)) = true.
Proof.
  induction t as [val | l IHl r IHr];
    intros i old_val old_path new_val Hgen; simpl in Hgen.
  - (* Leaf *)
    destruct (i =? 0) eqn:Hi; [| discriminate].
    inversion Hgen; subst.
    unfold verify; simpl. apply Nat.eqb_refl.
  - (* Node *)
    destruct (i <? num_leaves l) eqn:Hlt.
    + (* left subtree *)
      destruct (gen_proof l i) as [[v' p']|] eqn:Hgl; [| discriminate].
      inversion Hgen; subst.
      unfold verify. rewrite reconstruct_app_GoRight.
      simpl set_leaf. rewrite Hlt. simpl root.
      specialize (IHl _ _ _ new_val Hgl). unfold verify in IHl.
      apply Nat.eqb_eq in IHl. rewrite IHl.
      apply Nat.eqb_refl.
    + (* right subtree *)
      destruct (gen_proof r (i - num_leaves l)) as [[v' p']|] eqn:Hgr;
        [| discriminate].
      inversion Hgen; subst.
      unfold verify. rewrite reconstruct_app_GoLeft.
      simpl set_leaf. rewrite Hlt. simpl root.
      specialize (IHr _ _ _ new_val Hgr). unfold verify in IHr.
      apply Nat.eqb_eq in IHr. rewrite IHr.
      apply Nat.eqb_refl.
Qed.

Theorem gen_proof_path_length : forall t i v p,
  gen_proof t i = Some (v, p) ->
  leaf_depth t i = Some (length p).
Proof.
  induction t as [val | l IHl r IHr];
    intros i v p Hgen; simpl in *.
  - destruct (i =? 0) eqn:Hi; [| discriminate].
    inversion Hgen; subst. reflexivity.
  - destruct (i <? num_leaves l) eqn:Hlt.
    + destruct (gen_proof l i) as [[v' p']|] eqn:Hgl; [| discriminate].
      inversion Hgen; subst.
      specialize (IHl _ _ _ Hgl). rewrite IHl.
      f_equal. rewrite app_length. simpl. lia.
    + destruct (gen_proof r (i - num_leaves l)) as [[v' p']|] eqn:Hgr;
        [| discriminate].
      inversion Hgen; subst.
      specialize (IHr _ _ _ Hgr). rewrite IHr.
      f_equal. rewrite app_length. simpl. lia.
Qed.
'''

def main():
    with open("/app/MerkleTree.v", "w") as f:
        f.write(SOLUTION)
    print("Solution written to /app/MerkleTree.v")

if __name__ == "__main__":
    main()

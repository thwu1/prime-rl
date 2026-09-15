
(* MerkleTree.v — Formalization of Merkle hash trees with
   cryptographic security properties. Complete all five unfinished
   theorem proofs at the end of this file. *)

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
(* A direction indicates where the sibling hash is placed:           *)
(*   GoLeft  = sibling goes on the left:  hash(sibling, accum)       *)
(*   GoRight = sibling goes on the right: hash(accum, sibling)       *)
(* ================================================================ *)

Inductive dir : Type := GoLeft | GoRight.

Definition auth_path := list (dir * nat).

(* Reconstruct the root from a leaf value and an authentication path *)
Fixpoint reconstruct (v : nat) (p : auth_path) : nat :=
  match p with
  | nil => v
  | (GoLeft, s) :: rest => reconstruct (hash s v) rest
  | (GoRight, s) :: rest => reconstruct (hash v s) rest
  end.

(* Verify a leaf value against an expected root via an auth path *)
Definition verify (v : nat) (p : auth_path) (expected_root : nat) : bool :=
  (reconstruct v p) =? expected_root.

(* ================================================================ *)
(* Proof Generation and Leaf Access                                  *)
(* ================================================================ *)

(* Retrieve the i-th leaf value *)
Fixpoint get_leaf (t : tree) (i : nat) : option nat :=
  match t with
  | Leaf v => if i =? 0 then Some v else None
  | Node l r =>
    if i <? num_leaves l then get_leaf l i
    else get_leaf r (i - num_leaves l)
  end.

(* Generate an authentication path for the i-th leaf.
   Returns Some (leaf_value, authentication_path) or None if i is
   out of range. The path is ordered bottom-up (leaf to root). *)
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

(* Update the i-th leaf to a new value *)
Fixpoint set_leaf (t : tree) (i : nat) (new_val : nat) : tree :=
  match t with
  | Leaf _ => Leaf new_val
  | Node l r =>
    if i <? num_leaves l then Node (set_leaf l i new_val) r
    else Node l (set_leaf r (i - num_leaves l) new_val)
  end.

(* ================================================================ *)
(* Theorems to Prove                                                 *)
(*                                                                   *)
(* Complete every unfinished proof below.                             *)
(* You may add helper lemmas anywhere above the theorems.            *)
(* Do NOT add new Axiom or Parameter declarations.                   *)
(* ================================================================ *)

(* Theorem 1: COMPLETENESS
   Authentication paths produced by gen_proof verify successfully
   against the tree's root hash. *)
Theorem completeness : forall t i v p,
  gen_proof t i = Some (v, p) ->
  verify v p (root t) = true.
Proof.
  Admitted.

(* Theorem 2: BINDING (Position Binding)
   Under collision resistance, a single authentication path cannot
   verify two distinct leaf values against the same root hash.
   This is the core security property of Merkle tree commitments. *)
Theorem binding : forall p v1 v2 r,
  verify v1 p r = true ->
  verify v2 p r = true ->
  v1 = v2.
Proof.
  Admitted.

(* Theorem 3: LEAF EXTRACTION
   gen_proof returns the actual value stored at the queried leaf. *)
Theorem gen_proof_extracts_leaf : forall t i v p,
  gen_proof t i = Some (v, p) ->
  get_leaf t i = Some v.
Proof.
  Admitted.

(* Theorem 4: UPDATE SOUNDNESS
   After a leaf update via set_leaf, the authentication path from
   the original tree can verify the NEW leaf value against the
   UPDATED root hash. Sibling hashes along the path are unchanged
   because only one leaf was modified. *)
Theorem update_soundness : forall t i old_val old_path new_val,
  gen_proof t i = Some (old_val, old_path) ->
  verify new_val old_path (root (set_leaf t i new_val)) = true.
Proof.
  Admitted.

(* Theorem 5: PATH LENGTH
   The length of the authentication path equals the depth of
   the leaf in the tree. *)
Theorem gen_proof_path_length : forall t i v p,
  gen_proof t i = Some (v, p) ->
  leaf_depth t i = Some (length p).
Proof.
  Admitted.

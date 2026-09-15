(* MultiLimbArith.v — Multi-limb integer arithmetic with carry propagation
   and modular reduction, inspired by fiat-crypto's Arithmetic.Core.

   This file defines associational and positional representations of
   multi-limb integers, operations (eval, mul, split, reduce),
   and states correctness lemmas. Several lemmas are stubbed with
   placeholder proofs and must be completed for the file to verify
   without shortcuts.

*)

From Coq Require Import ZArith Lia List Znumtheory.
Import ListNotations.
Local Open Scope Z_scope.

(* ================================================================== *)
(* Part 1: Associational representation                                *)
(* A number is a list of (weight, digit) pairs; its value is           *)
(*   sum of weight_i * digit_i                                         *)
(* ================================================================== *)

Module Assoc.
  Definition eval (p : list (Z * Z)) : Z :=
    fold_right (fun x acc => fst x * snd x + acc) 0 p.

  Lemma eval_nil : eval [] = 0.
  Proof. reflexivity. Qed.

  Lemma eval_cons a q : eval (a :: q) = fst a * snd a + eval q.
  Proof. reflexivity. Qed.

  Lemma eval_app p q : eval (p ++ q) = eval p + eval q.
  Proof.
    induction p as [| a p' IH]; simpl; [lia | rewrite IH; lia].
  Qed.

  (* Associational multiplication via flat_map *)
  Definition mul (p q : list (Z * Z)) : list (Z * Z) :=
    flat_map (fun t =>
      map (fun t' => (fst t * fst t', snd t * snd t')) q
    ) p.

  Lemma eval_mul p q : eval (mul p q) = eval p * eval q.
  Proof.
    induction p as [| t p' IH]; [reflexivity | ].
    simpl. rewrite eval_app, IH.
    assert (H : eval (map (fun t' => (fst t * fst t', snd t * snd t')) q) =
                fst t * snd t * eval q).
    { clear IH. induction q as [| t' q' IHq]; simpl; [lia | rewrite IHq; nia]. }
    rewrite H. nia.
  Qed.

  (* Negate all digits *)
  Definition negate_snd (p : list (Z * Z)) : list (Z * Z) :=
    map (fun t => (fst t, - snd t)) p.

  Lemma eval_negate_snd p : eval (negate_snd p) = - eval p.
  Proof.
    induction p as [| t p' IH]; [reflexivity | ].
    simpl. rewrite IH. nia.
  Qed.

  (* Split: separate terms whose weight is divisible by s *)
  Definition split (s : Z) (p : list (Z * Z)) : list (Z * Z) * list (Z * Z) :=
    let hi_lo := partition (fun t => fst t mod s =? 0) p in
    (snd hi_lo, map (fun t => (fst t / s, snd t)) (fst hi_lo)).

  (* ============================================================ *)
  (* LEMMA 1 (stub): split preserves evaluation                    *)
  (* Prove that fst(split s p) + s * snd(split s p) = eval p      *)
  (* ============================================================ *)
  Lemma eval_split s p (s_nz : s <> 0) :
    eval (fst (split s p)) + s * eval (snd (split s p)) = eval p.
  Proof.
    (* STUB — must be completed *)
  Admitted.

  (* The fundamental reduction rule for modular arithmetic *)
  Lemma reduction_rule a b s c (mod_nz : s - c <> 0) :
    (a + s * b) mod (s - c) = (a + c * b) mod (s - c).
  Proof.
    replace (s * b) with (c * b + b * (s - c)) by lia.
    rewrite Z.add_assoc.
    rewrite Z.add_mod by lia.
    rewrite Z.mod_mul by lia.
    rewrite Z.add_0_r.
    rewrite Z.mod_mod by lia.
    reflexivity.
  Qed.

  (* Reduce: replace high terms using the reduction rule *)
  Definition reduce (s : Z) (c : list (Z * Z)) (p : list (Z * Z)) : list (Z * Z) :=
    let lo_hi := split s p in
    fst lo_hi ++ mul c (snd lo_hi).

  (* ============================================================ *)
  (* LEMMA 2 (stub): reduce preserves value mod (s - eval c)      *)
  (* ============================================================ *)
  Lemma eval_reduce s c p (s_nz : s <> 0) (mod_nz : s - eval c <> 0) :
    eval (reduce s c p) mod (s - eval c) = eval p mod (s - eval c).
  Proof.
    (* STUB — must be completed *)
  Admitted.

End Assoc.

(* ================================================================== *)
(* Part 2: Positional representation                                   *)
(* A number in positional form is a list of digits with a weight       *)
(* function weight : nat -> Z.                                         *)
(* ================================================================== *)

Module Pos.
  Section WithWeight.
    Variable weight : nat -> Z.

    (* Weight function properties *)
    Hypothesis weight_0 : weight 0%nat = 1.
    Hypothesis weight_positive : forall i, 0 < weight i.
    Hypothesis weight_divides : forall i, (weight i | weight (S i)).

    Definition eval (n : nat) (xs : list Z) : Z :=
      fold_right (fun p acc => fst p * snd p + acc) 0
        (combine (map weight (seq 0 n)) xs).

    Lemma eval_nil n : eval n [] = 0.
    Proof.
      unfold eval. destruct n; reflexivity.
    Qed.

    (* Convert positional to associational *)
    Definition to_assoc (n : nat) (xs : list Z) : list (Z * Z) :=
      combine (map weight (seq 0 n)) xs.

    Lemma eval_to_assoc n xs :
      eval n xs = Assoc.eval (to_assoc n xs).
    Proof.
      unfold eval, to_assoc, Assoc.eval. reflexivity.
    Qed.

    (* Partition: decompose an integer into positional digits *)
    Definition partition_val (n : nat) (x : Z) : list Z :=
      map (fun i => (x mod weight (S i)) / weight i) (seq 0 n).

    Lemma length_partition_val n x : length (partition_val n x) = n.
    Proof.
      unfold partition_val. rewrite map_length, seq_length. reflexivity.
    Qed.

    (* ============================================================ *)
    (* LEMMA 3 (stub): partition correctly decomposes a value        *)
    (* eval n (partition_val n x) = x mod weight(n)                  *)
    (* ============================================================ *)
    Lemma eval_partition n x :
      eval n (partition_val n x) = x mod weight n.
    Proof.
      (* STUB — must be completed *)
    Admitted.

    (* ============================================================ *)
    (* LEMMA 4 (stub): Partition digits are bounded                  *)
    (* Each digit d_i satisfies 0 <= d_i < weight(i+1)/weight(i)    *)
    (* ============================================================ *)
    Lemma partition_bounded n x i (Hi : (i < n)%nat) (Hx : 0 <= x) :
      let d := nth i (partition_val n x) 0 in
      0 <= d < weight (S i) / weight i.
    Proof.
      (* STUB — must be completed *)
    Admitted.

  End WithWeight.
End Pos.

(* ================================================================== *)
(* Part 3: Uniform-base weight function (base 2^w)                    *)
(* ================================================================== *)

Module UWeight.
  Definition uweight (lgr : Z) (i : nat) : Z := 2 ^ (lgr * Z.of_nat i).

  Lemma uweight_0 lgr : uweight lgr 0 = 1.
  Proof.
    unfold uweight. rewrite Z.mul_0_r. reflexivity.
  Qed.

  Lemma uweight_positive lgr (Hr : 0 < lgr) i : 0 < uweight lgr i.
  Proof.
    unfold uweight. apply Z.pow_pos_nonneg; lia.
  Qed.

  Lemma uweight_S lgr (Hr : 0 < lgr) i :
    uweight lgr (S i) = 2 ^ lgr * uweight lgr i.
  Proof.
    unfold uweight.
    rewrite Nat2Z.inj_succ, Z.mul_succ_r.
    rewrite Z.pow_add_r by lia.
    ring.
  Qed.

  (* ============================================================ *)
  (* LEMMA 5 (stub): uweight divides its successor                 *)
  (* ============================================================ *)
  Lemma uweight_divides lgr (Hr : 0 < lgr) i :
    (uweight lgr i | uweight lgr (S i)).
  Proof.
    (* STUB — must be completed *)
  Admitted.

  (* ============================================================ *)
  (* LEMMA 6 (stub): uweight of sum equals product                 *)
  (* uweight lgr (i + j) = uweight lgr i * uweight lgr j           *)
  (* ============================================================ *)
  Lemma uweight_sum lgr (Hr : 0 <= lgr) i j :
    uweight lgr (i + j) = uweight lgr i * uweight lgr j.
  Proof.
    (* STUB — must be completed *)
  Admitted.

  (* ============================================================ *)
  (* LEMMA 7 (stub): modular reduction via uweight                 *)
  (* For a value x and base 2^lgr with n limbs,                   *)
  (* (x mod uweight lgr n) mod uweight lgr m = x mod uweight lgr m *)
  (* when m <= n                                                   *)
  (* ============================================================ *)
  Lemma uweight_mod_mod lgr (Hr : 0 < lgr) x m n (Hmn : (m <= n)%nat) :
    (x mod uweight lgr n) mod uweight lgr m = x mod uweight lgr m.
  Proof.
    (* STUB — must be completed *)
  Admitted.

End UWeight.

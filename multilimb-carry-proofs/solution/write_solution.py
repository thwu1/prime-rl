#!/usr/bin/env python3

"""Write the completed MultiLimbArith.v with all 7 proofs filled in."""

SOLUTION = r'''(* MultiLimbArith.v — Multi-limb integer arithmetic with carry propagation
   and modular reduction, inspired by fiat-crypto's Arithmetic.Core.

   This file defines associational and positional representations of
   multi-limb integers, operations (eval, mul, split, reduce),
   and states correctness lemmas. All lemmas are fully proved.

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

  (* LEMMA 1: eval_split *)
  Lemma eval_split s p (s_nz : s <> 0) :
    eval (fst (split s p)) + s * eval (snd (split s p)) = eval p.
  Proof.
    unfold split.
    induction p as [| a p' IH].
    - simpl. lia.
    - simpl partition.
      destruct (partition (fun t => fst t mod s =? 0) p') as [hi lo].
      simpl in IH |- *.
      destruct (fst a mod s =? 0) eqn:Heq; simpl.
      + rewrite Z.eqb_eq in Heq.
        assert (Hdiv: s * (fst a / s) = fst a).
        { pose proof (Z.div_mod (fst a) s s_nz). rewrite Heq in *. lia. }
        nia.
      + nia.
  Qed.

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

  (* LEMMA 2: eval_reduce *)
  Lemma eval_reduce s c p (s_nz : s <> 0) (mod_nz : s - eval c <> 0) :
    eval (reduce s c p) mod (s - eval c) = eval p mod (s - eval c).
  Proof.
    unfold reduce.
    rewrite eval_app, eval_mul.
    rewrite <- (eval_split s p s_nz).
    symmetry.
    apply reduction_rule. assumption.
  Qed.

End Assoc.

(* ================================================================== *)
(* Part 2: Positional representation                                   *)
(* A number in positional form is a list of digits with a weight       *)
(* function weight : nat -> Z.                                         *)
(* ================================================================== *)

(* Helper lemmas used in proofs *)
Lemma combine_app_helper {A B} (l1 l2 : list A) (l3 l4 : list B)
  (Hlen : length l1 = length l3) :
  combine (l1 ++ l2) (l3 ++ l4) = combine l1 l3 ++ combine l2 l4.
Proof.
  revert l3 Hlen. induction l1 as [| a l1' IH]; intros.
  - destruct l3; [reflexivity | discriminate].
  - destruct l3 as [| b l3']; [discriminate | ].
    simpl in Hlen. injection Hlen as Hlen'.
    simpl. f_equal. apply IH. exact Hlen'.
Qed.

Lemma fold_right_add_base {A} (f : A -> Z) base (l : list A) :
  fold_right (fun x acc => f x + acc) base l =
  fold_right (fun x acc => f x + acc) 0 l + base.
Proof.
  induction l as [| a l' IH]; simpl; lia.
Qed.

Lemma nth_map_seq (f : nat -> Z) (n i : nat) (d : Z) (Hi : (i < n)%nat) :
  nth i (map f (seq 0 n)) d = f i.
Proof.
  rewrite (nth_indep _ d (f 0%nat))
    by (rewrite map_length, seq_length; lia).
  rewrite map_nth, seq_nth by lia.
  reflexivity.
Qed.

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

    (* LEMMA 3: eval_partition *)
    Lemma eval_partition n x :
      eval n (partition_val n x) = x mod weight n.
    Proof.
      unfold eval, partition_val.
      induction n as [| n' IH].
      - simpl. rewrite weight_0, Z.mod_1_r. lia.
      - rewrite seq_S, !map_app.
        rewrite combine_app_helper
          by (rewrite map_length, map_length, !seq_length; reflexivity).
        rewrite fold_right_app.
        simpl combine. simpl fold_right.
        rewrite (fold_right_add_base (fun p => fst p * snd p)).
        rewrite IH.
        rewrite Z.add_0_r.
        assert (Hwd : (weight n' | weight (S n'))) by apply weight_divides.
        assert (Hwp : 0 < weight n') by apply weight_positive.
        assert (HwSp : 0 < weight (S n')) by apply weight_positive.
        assert (Hmod_mod : x mod weight (S n') mod weight n' = x mod weight n').
        { symmetry. apply Znumtheory.Zmod_div_mod; try lia.
          destruct Hwd as [k Hk]. exists k. lia. }
        pose proof (Z.div_mod (x mod weight (S n')) (weight n') ltac:(lia)) as Hdm.
        rewrite Hmod_mod in Hdm.
        lia.
    Qed.

    (* LEMMA 4: partition_bounded *)
    Lemma partition_bounded n x i (Hi : (i < n)%nat) (Hx : 0 <= x) :
      let d := nth i (partition_val n x) 0 in
      0 <= d < weight (S i) / weight i.
    Proof.
      simpl. unfold partition_val.
      rewrite nth_map_seq by lia.
      set (w := weight (S i)).
      set (wi := weight i).
      assert (Hwi_pos : 0 < wi) by apply weight_positive.
      assert (Hw_pos : 0 < w) by apply weight_positive.
      assert (Hdiv : (wi | w)) by apply weight_divides.
      assert (Hq_pos : 0 < w / wi).
      { destruct Hdiv as [k Hk]. rewrite Hk. rewrite Z.div_mul by lia.
        destruct (Z.eq_dec k 0); [subst; lia | nia]. }
      split.
      - apply Z.div_pos; try lia. apply Z.mod_pos_bound. lia.
      - apply Z.div_lt_upper_bound; try lia.
        assert (Hmul : wi * (w / wi) = w).
        { destruct Hdiv as [k Hk]. rewrite Hk. rewrite Z.div_mul by lia. lia. }
        rewrite Hmul. apply Z.mod_pos_bound. lia.
    Qed.

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

  (* LEMMA 5: uweight_divides *)
  Lemma uweight_divides lgr (Hr : 0 < lgr) i :
    (uweight lgr i | uweight lgr (S i)).
  Proof.
    rewrite uweight_S by lia.
    exists (2 ^ lgr). ring.
  Qed.

  (* LEMMA 6: uweight_sum *)
  Lemma uweight_sum lgr (Hr : 0 <= lgr) i j :
    uweight lgr (i + j) = uweight lgr i * uweight lgr j.
  Proof.
    unfold uweight.
    rewrite Nat2Z.inj_add, Z.mul_add_distr_l.
    rewrite Z.pow_add_r by nia.
    ring.
  Qed.

  (* LEMMA 7: uweight_mod_mod *)
  Lemma uweight_mod_mod lgr (Hr : 0 < lgr) x m n (Hmn : (m <= n)%nat) :
    (x mod uweight lgr n) mod uweight lgr m = x mod uweight lgr m.
  Proof.
    symmetry.
    apply Znumtheory.Zmod_div_mod.
    - apply uweight_positive; lia.
    - apply uweight_positive; lia.
    - exists (2 ^ (lgr * (Z.of_nat n - Z.of_nat m))).
      unfold uweight.
      rewrite <- Z.pow_add_r by nia.
      f_equal. lia.
  Qed.

End UWeight.
'''

with open('/app/MultiLimbArith.v', 'w') as f:
    f.write(SOLUTION)

print("Solution written to /app/MultiLimbArith.v")


(** MultiLimbArith.v — Self-contained multi-limb modular arithmetic library.
    Inspired by MIT PLV's fiat-crypto Arithmetic/Core.v.

    Defines associational and positional representations of multi-limb
    integers, with operations for evaluation, multiplication, negation,
    scaling, carry propagation, reversal, partition, and addition.
    Also defines a uniform-weight (radix 2^w) system.

    12 lemmas are [Admitted]. Replace every [Admitted] with a valid Coq
    proof so that [coqc] accepts the file with no errors. *)

From Coq Require Import ZArith Lia List.
Import ListNotations.
Local Open Scope Z_scope.
Local Open Scope list_scope.

(* ================================================================ *)
(* Utility lemmas (all proved)                                       *)
(* ================================================================ *)

Lemma fold_right_add_app (l1 l2 : list Z) :
  fold_right Z.add 0 (l1 ++ l2) =
  fold_right Z.add 0 l1 + fold_right Z.add 0 l2.
Proof. induction l1 as [|x xs IH]; simpl; lia. Qed.

Lemma combine_app_same {A B : Type} (l1 l2 : list A) (r1 r2 : list B) :
  length l1 = length r1 ->
  combine (l1 ++ l2) (r1 ++ r2) = combine l1 r1 ++ combine l2 r2.
Proof.
  revert r1; induction l1 as [|x xs IH]; intros [|y ys] Hlen;
    simpl in *; try lia; auto.
  f_equal. apply IH. lia.
Qed.

Lemma seq_snoc_r (start len : nat) :
  seq start (S len) = seq start len ++ [(start + len)%nat].
Proof.
  revert start; induction len as [|len IH]; intro start.
  - simpl. f_equal. lia.
  - change (seq start (S (S len))) with (start :: seq (S start) (S len)).
    rewrite IH.
    change (seq start (S len)) with (start :: seq (S start) len).
    rewrite <- app_comm_cons.
    replace (S start + len)%nat with (start + S len)%nat by lia.
    reflexivity.
Qed.

Lemma mod_mod_same (a b : Z) (Hb : 0 < b) :
  (a mod b) mod b = a mod b.
Proof. apply Z.mod_small. apply Z.mod_pos_bound. lia. Qed.

Lemma mod_mod_divides (a b c : Z)
  (Hb : 0 < b) (Hc : 0 < c) (Hdiv : c mod b = 0) :
  (a mod c) mod b = a mod b.
Proof.
  symmetry.
  rewrite (Z.div_mod a c) at 1 by lia.
  rewrite Z.add_mod by lia.
  rewrite Z.mul_mod by lia.
  rewrite Hdiv, Z.mul_0_l, Z.mod_0_l, Z.add_0_l by lia.
  apply mod_mod_same. lia.
Qed.

(* ================================================================ *)
(* Module Assoc: Associational representation                        *)
(* ================================================================ *)

Module Assoc.
  Definition eval (p : list (Z * Z)) : Z :=
    fold_right Z.add 0 (map (fun t => fst t * snd t) p).

  Lemma eval_nil : eval nil = 0.
  Proof. reflexivity. Qed.

  Lemma eval_cons (a : Z * Z) (q : list (Z * Z)) :
    eval (a :: q) = fst a * snd a + eval q.
  Proof. reflexivity. Qed.

  Lemma eval_app (p q : list (Z * Z)) :
    eval (p ++ q) = eval p + eval q.
  Proof. unfold eval. rewrite map_app, fold_right_add_app. reflexivity. Qed.

  (* ---- Multiplication ---- *)

  Definition mul (p q : list (Z * Z)) : list (Z * Z) :=
    flat_map (fun t =>
      map (fun t' => (fst t * fst t', snd t * snd t')) q) p.

  Lemma mul_cons (a : Z * Z) (ps q : list (Z * Z)) :
    mul (a :: ps) q =
    map (fun t' => (fst a * fst t', snd a * snd t')) q ++ mul ps q.
  Proof. reflexivity. Qed.

  Lemma eval_map_mul_inner (a : Z * Z) (q : list (Z * Z)) :
    eval (map (fun t' => (fst a * fst t', snd a * snd t')) q)
    = fst a * snd a * eval q.
  Proof.
    induction q as [|b qs IHq].
    - unfold eval; simpl; lia.
    - change (map (fun t' : Z * Z => (fst a * fst t', snd a * snd t')) (b :: qs))
        with ((fst a * fst b, snd a * snd b)
              :: map (fun t' => (fst a * fst t', snd a * snd t')) qs).
      rewrite !eval_cons, IHq. simpl. ring.
  Qed.

  (** ADMITTED 1 *)
  Lemma eval_mul (p q : list (Z * Z)) :
    eval (mul p q) = eval p * eval q.
  Proof.
    induction p as [|a ps IH].
    - reflexivity.
    - rewrite mul_cons, eval_app, IH, eval_cons.
      rewrite eval_map_mul_inner. nia.
  Qed.

  (* ---- Negation ---- *)

  Definition negate_snd (p : list (Z * Z)) : list (Z * Z) :=
    map (fun t => (fst t, - snd t)) p.

  (** ADMITTED 2 *)
  Lemma eval_negate_snd (p : list (Z * Z)) :
    eval (negate_snd p) = - eval p.
  Proof.
    induction p as [|a ps IH].
    - reflexivity.
    - change (negate_snd (a :: ps))
        with ((fst a, - snd a) :: negate_snd ps).
      rewrite !eval_cons, IH. simpl. ring.
  Qed.

  (* ---- Scaling ---- *)

  (** ADMITTED 3: eval of uniformly-scaled pairs. *)
  Lemma eval_map_scale (a x : Z) (p : list (Z * Z)) :
    eval (map (fun t => (a * fst t, x * snd t)) p) = a * x * eval p.
  Proof.
    induction p as [|[w v] ps IH].
    - unfold eval; simpl; ring.
    - change (map (fun t : Z * Z => (a * fst t, x * snd t)) ((w, v) :: ps))
        with ((a * w, x * v) :: map (fun t => (a * fst t, x * snd t)) ps).
      rewrite !eval_cons, IH. simpl. ring.
  Qed.

  (* ---- Carry ---- *)

  Definition carryterm (w fw : Z) (t : Z * Z) : list (Z * Z) :=
    if (fst t =? w)
    then [(w * fw, snd t / fw); (w, snd t mod fw)]
    else [t].

  Lemma eval_carryterm (w fw : Z) (t : Z * Z) (fw_nz : fw <> 0) :
    eval (carryterm w fw t) = eval [t].
  Proof.
    unfold carryterm.
    destruct (fst t =? w) eqn:E.
    - apply Z.eqb_eq in E. rewrite !eval_cons, eval_nil. simpl.
      pose proof (Z.div_mod (snd t) fw fw_nz).
      rewrite E. nia.
    - reflexivity.
  Qed.

  Definition carry (w fw : Z) (p : list (Z * Z)) : list (Z * Z) :=
    flat_map (carryterm w fw) p.

  Lemma carry_cons (w fw : Z) (a : Z * Z) (ps : list (Z * Z)) :
    carry w fw (a :: ps) = carryterm w fw a ++ carry w fw ps.
  Proof. reflexivity. Qed.

  (** ADMITTED 4 *)
  Lemma eval_carry (w fw : Z) (p : list (Z * Z)) (fw_nz : fw <> 0) :
    eval (carry w fw p) = eval p.
  Proof.
    induction p as [|a ps IH].
    - reflexivity.
    - rewrite carry_cons, eval_app, IH, eval_cons.
      rewrite eval_carryterm by assumption.
      rewrite eval_cons, eval_nil. lia.
  Qed.

  (* ---- Reversal ---- *)

  (** ADMITTED 5: evaluation is order-independent. *)
  Lemma eval_rev (p : list (Z * Z)) :
    eval (rev p) = eval p.
  Proof.
    induction p as [|a ps IH].
    - reflexivity.
    - change (rev (a :: ps)) with (rev ps ++ [a]).
      rewrite eval_app, IH.
      rewrite !eval_cons, eval_nil. lia.
  Qed.

  (* ---- Reduction rule (proved, not admitted) ---- *)

  Lemma reduction_rule' (b s c : Z) (mod_nz : s - c <> 0) :
    (s * b) mod (s - c) = (c * b) mod (s - c).
  Proof.
    replace (s * b) with (c * b + b * (s - c)) by lia.
    rewrite Z.add_mod, Z_mod_mult, Z.add_0_r, Z.mod_mod by trivial.
    reflexivity.
  Qed.

  Lemma reduction_rule (a b s c : Z) (mod_nz : s - c <> 0) :
    (a + s * b) mod (s - c) = (a + c * b) mod (s - c).
  Proof.
    rewrite Z.add_mod with (b := s * b), Z.add_mod with (b := c * b)
      by trivial.
    rewrite reduction_rule' by trivial. reflexivity.
  Qed.

End Assoc.

(* ================================================================ *)
(* Module Pos: Positional representation                             *)
(* ================================================================ *)

Module Pos.
  Section WithWeight.
    Context (weight : nat -> Z).
    Context (weight_0 : weight 0%nat = 1).
    Context (weight_nz : forall i, weight i <> 0).
    Context (weight_pos : forall i, 0 < weight i).
    Context (weight_mul : forall i, weight (S i) mod weight i = 0).
    Context (weight_div : forall i, 0 < weight (S i) / weight i).

    Definition to_assoc (n : nat) (xs : list Z) : list (Z * Z) :=
      combine (map weight (seq 0 n)) xs.

    Definition eval (n : nat) (xs : list Z) : Z :=
      Assoc.eval (to_assoc n xs).

    Lemma eval_nil (n : nat) : eval n [] = 0.
    Proof. unfold eval, to_assoc. rewrite combine_nil. reflexivity. Qed.

    Lemma eval_0 (xs : list Z) : eval 0 xs = 0.
    Proof. reflexivity. Qed.

    (** ADMITTED 6 *)
    Lemma eval_snoc (n : nat) (x : list Z) (y : Z) :
      length x = n ->
      eval (S n) (x ++ [y]) = eval n x + weight n * y.
    Proof.
      intros Hlen. unfold eval, to_assoc, Assoc.eval.
      rewrite seq_snoc_r.
      replace (0 + n)%nat with n by lia.
      rewrite map_app, combine_app_same, map_app, fold_right_add_app
        by (rewrite map_length, seq_length; lia).
      simpl. lia.
    Qed.

    Definition zeros (n : nat) : list Z := repeat 0 n.

    Lemma length_zeros (n : nat) : length (zeros n) = n.
    Proof. apply repeat_length. Qed.

    Lemma eval_zeros (n : nat) : eval n (zeros n) = 0.
    Proof.
      unfold eval, to_assoc, zeros, Assoc.eval.
      cut (forall s, fold_right Z.add 0
        (map (fun t : Z * Z => fst t * snd t)
          (combine (map weight (seq s n)) (repeat 0 n))) = 0).
      { intro H; apply H. }
      induction n as [|n IH]; intro s; [reflexivity|].
      cbn [seq repeat combine map fold_right fst snd].
      rewrite IH. lia.
    Qed.

    (** Partition: decompose a value into n limbs. *)
    Definition part (n : nat) (x : Z) : list Z :=
      map (fun i => (x mod weight (S i)) / weight i) (seq 0 n).

    Lemma length_part (n : nat) (x : Z) : length (part n x) = n.
    Proof. unfold part. rewrite map_length, seq_length. reflexivity. Qed.

    (** ADMITTED 7: partition evaluation equals x mod weight n. *)
    Lemma eval_part (n : nat) (x : Z) :
      eval n (part n x) = x mod weight n.
    Proof.
      induction n as [|n IH].
      - change (part 0 x) with (nil : list Z).
        unfold eval, to_assoc, Assoc.eval. simpl.
        rewrite weight_0. symmetry. apply Z.mod_1_r.
      - unfold part. rewrite seq_snoc_r.
        replace (0 + n)%nat with n by lia.
        rewrite map_app. simpl.
        change (map (fun i : nat => x mod weight (S i) / weight i) (seq 0 n))
          with (part n x).
        rewrite eval_snoc by (rewrite length_part; reflexivity).
        rewrite IH.
        pose proof (weight_pos n).
        pose proof (weight_pos (S n)).
        pose proof (weight_mul n) as Hm.
        pose proof (Z.div_mod (x mod weight (S n)) (weight n) ltac:(lia)) as Hdm.
        assert (Hmod : x mod weight n = (x mod weight (S n)) mod weight n).
        { symmetry. apply mod_mod_divides;
          [exact (weight_pos n) | exact (weight_pos (S n)) | exact Hm]. }
        lia.
    Qed.

    (** Positional addition. *)
    Fixpoint add_lists (a b : list Z) : list Z :=
      match a, b with
      | [], _ => b
      | _, [] => a
      | x :: xs, y :: ys => (x + y) :: add_lists xs ys
      end.

    Lemma length_add_lists (a b : list Z) :
      length a = length b ->
      length (add_lists a b) = length a.
    Proof.
      revert b; induction a as [|x xs IH]; intros [|y ys] Hlen;
        simpl in *; try lia.
      f_equal. apply IH. lia.
    Qed.

    (* Helper: generalize over the weight list for add_lists *)
    Lemma eval_combine_add (ws : list Z) (a b : list Z) :
      length a = length ws -> length b = length ws ->
      Assoc.eval (combine ws (add_lists a b)) =
      Assoc.eval (combine ws a) + Assoc.eval (combine ws b).
    Proof.
      revert a b; induction ws as [|w rest IH];
        intros [|xa xs] [|xb ys] Ha Hb; simpl in *; try lia;
        try reflexivity.
      rewrite !Assoc.eval_cons, IH by lia. simpl. ring.
    Qed.

    (** ADMITTED 8: positional addition correctness. *)
    Lemma eval_add_lists (n : nat) (a b : list Z) :
      length a = n -> length b = n ->
      eval n (add_lists a b) = eval n a + eval n b.
    Proof.
      intros Ha Hb. unfold eval, to_assoc.
      apply eval_combine_add; rewrite map_length, seq_length; lia.
    Qed.

  End WithWeight.
End Pos.

(* ================================================================ *)
(* Module UWeight: uniform-weight radix-2^w system                   *)
(* ================================================================ *)

Module UWeight.
  Definition uweight (lgr : Z) (i : nat) : Z :=
    2 ^ (lgr * Z.of_nat i).

  (** ADMITTED 9 *)
  Lemma uweight_0 (lgr : Z) : uweight lgr 0 = 1.
  Proof. unfold uweight. rewrite Z.mul_0_r. reflexivity. Qed.

  (** ADMITTED 10 *)
  Lemma uweight_S (lgr : Z) (H : 0 <= lgr) (i : nat) :
    uweight lgr (S i) = 2 ^ lgr * uweight lgr i.
  Proof.
    unfold uweight.
    replace (lgr * Z.of_nat (S i)) with (lgr + lgr * Z.of_nat i) by lia.
    rewrite Z.pow_add_r by nia.
    reflexivity.
  Qed.

  Lemma uweight_pos (lgr : Z) (H : 0 < lgr) (i : nat) :
    0 < uweight lgr i.
  Proof. unfold uweight. apply Z.pow_pos_nonneg; lia. Qed.

  Lemma uweight_nz (lgr : Z) (H : 0 < lgr) (i : nat) :
    uweight lgr i <> 0.
  Proof. pose proof (uweight_pos lgr H i). lia. Qed.

  (** ADMITTED 11 *)
  Lemma uweight_mul (lgr : Z) (H : 0 < lgr) (i : nat) :
    uweight lgr (S i) mod uweight lgr i = 0.
  Proof.
    unfold uweight.
    replace (lgr * Z.of_nat (S i)) with (lgr * Z.of_nat i + lgr) by lia.
    rewrite Z.pow_add_r by nia.
    rewrite Z.mul_comm.
    apply Z_mod_mult.
  Qed.

  Lemma uweight_div (lgr : Z) (H : 0 < lgr) (i : nat) :
    0 < uweight lgr (S i) / uweight lgr i.
  Proof.
    pose proof (uweight_pos lgr H i).
    pose proof (uweight_pos lgr H (S i)).
    rewrite uweight_S by lia.
    rewrite Z.div_mul by lia.
    apply Z.pow_pos_nonneg; lia.
  Qed.

  (** ADMITTED 12 *)
  Lemma uweight_sum (lgr : Z) (H : 0 <= lgr) (i j : nat) :
    uweight lgr (i + j) = uweight lgr i * uweight lgr j.
  Proof.
    unfold uweight.
    rewrite Nat2Z.inj_add, Z.mul_add_distr_l.
    rewrite Z.pow_add_r by nia.
    reflexivity.
  Qed.

End UWeight.

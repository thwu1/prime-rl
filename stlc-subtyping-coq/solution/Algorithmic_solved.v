(* Algorithmic.v - SOLVED *)

Require Export Typing.
Require Import Coq.Bool.Bool.
Require Import Coq.Strings.String.

(** Decidability of subtyping — mutual recursion on S *)
Fixpoint sub_dec (S T : ty) {struct S} : bool :=
  match S, T with
  | _, Ty_Top => true
  | Ty_Unit, Ty_Unit => true
  | Ty_Arrow S1 S2, Ty_Arrow T1 T2 => sub_dec_rev S1 T1 && sub_dec S2 T2
  | Ty_Prod S1 S2, Ty_Prod T1 T2 => sub_dec S1 T1 && sub_dec S2 T2
  | _, _ => false
  end
with sub_dec_rev (S T : ty) {struct S} : bool :=
  match S with
  | Ty_Top => true
  | Ty_Arrow S1 S2 =>
      match T with
      | Ty_Arrow T1 T2 => sub_dec S1 T1 && sub_dec_rev S2 T2
      | _ => false
      end
  | Ty_Prod S1 S2 =>
      match T with
      | Ty_Prod T1 T2 => sub_dec_rev S1 T1 && sub_dec_rev S2 T2
      | _ => false
      end
  | Ty_Unit =>
      match T with Ty_Unit => true | _ => false end
  end.

Lemma sub_dec_props : forall S,
  (forall T, sub_dec S T = true -> S <: T) /\
  (forall T, sub_dec_rev S T = true -> T <: S).
Proof.
  induction S as [|S1 [IH1s IH1r] S2 [IH2s IH2r]|S1 [IH1s IH1r] S2 [IH2s IH2r]|].
  - (* Ty_Top *)
    split; intros T H; simpl in H.
    + destruct T; try discriminate; auto.
    + auto.
  - (* Ty_Arrow *)
    split; intros T H; simpl in H.
    + destruct T; try discriminate; auto.
      apply andb_true_iff in H. destruct H.
      constructor; auto.
    + destruct T; try discriminate.
      apply andb_true_iff in H. destruct H.
      constructor; auto.
  - (* Ty_Prod *)
    split; intros T H; simpl in H.
    + destruct T; try discriminate; auto.
      apply andb_true_iff in H. destruct H.
      constructor; auto.
    + destruct T; try discriminate.
      apply andb_true_iff in H. destruct H.
      constructor; auto.
  - (* Ty_Unit *)
    split; intros T H; simpl in H.
    + destruct T; try discriminate; auto.
    + destruct T; try discriminate; auto.
Qed.

Lemma sub_dec_sound : forall S T,
  sub_dec S T = true -> S <: T.
Proof. intros. apply (proj1 (sub_dec_props S)). exact H. Qed.

Lemma sub_dec_rev_sound : forall S T,
  sub_dec_rev S T = true -> T <: S.
Proof. intros. apply (proj2 (sub_dec_props S)). exact H. Qed.

Lemma sub_dec_complete_pair : forall S T,
  S <: T -> sub_dec S T = true /\ sub_dec_rev T S = true.
Proof.
  intros S T H. induction H.
  - (* S_Refl *)
    induction T; simpl; auto.
    + destruct IHT1 as [? ?]. destruct IHT2 as [? ?].
      split; apply andb_true_iff; auto.
    + destruct IHT1 as [? ?]. destruct IHT2 as [? ?].
      split; apply andb_true_iff; auto.
  - (* S_Top *) simpl. split; auto. destruct S; auto.
  - (* S_Arrow *)
    destruct IHsubtype1 as [IH1s IH1r].
    destruct IHsubtype2 as [IH2s IH2r].
    simpl. split; apply andb_true_iff; auto.
  - (* S_Prod *)
    destruct IHsubtype1 as [IH1s IH1r].
    destruct IHsubtype2 as [IH2s IH2r].
    simpl. split; apply andb_true_iff; auto.
Qed.

Lemma sub_dec_complete : forall S T,
  S <: T -> sub_dec S T = true.
Proof. intros. apply (proj1 (sub_dec_complete_pair S T H)). Qed.

(** Type equality decision *)
Fixpoint ty_eqb (T1 T2 : ty) : bool :=
  match T1, T2 with
  | Ty_Top, Ty_Top => true
  | Ty_Unit, Ty_Unit => true
  | Ty_Arrow S1 S2, Ty_Arrow T1 T2 => ty_eqb S1 T1 && ty_eqb S2 T2
  | Ty_Prod S1 S2, Ty_Prod T1 T2 => ty_eqb S1 T1 && ty_eqb S2 T2
  | _, _ => false
  end.

Lemma ty_eqb_refl : forall T, ty_eqb T T = true.
Proof. induction T; simpl; try rewrite IHT1; try rewrite IHT2; auto. Qed.

Lemma ty_eqb_eq : forall T1 T2, ty_eqb T1 T2 = true -> T1 = T2.
Proof.
  induction T1; destruct T2; simpl; intros; try discriminate;
  try reflexivity; apply andb_true_iff in H; destruct H; f_equal; auto.
Qed.

(** Algorithmic type checker *)
Fixpoint typecheck (Gamma : context) (t : tm) : option ty :=
  match t with
  | tm_var x => lookup x Gamma
  | tm_abs x T1 body =>
      match typecheck ((x, T1) :: Gamma) body with
      | Some T2 => Some (Ty_Arrow T1 T2)
      | None => None
      end
  | tm_app t1 t2 =>
      match typecheck Gamma t1, typecheck Gamma t2 with
      | Some (Ty_Arrow T11 T12), Some T2 =>
          if sub_dec T2 T11 then Some T12 else None
      | _, _ => None
      end
  | tm_pair t1 t2 =>
      match typecheck Gamma t1, typecheck Gamma t2 with
      | Some T1, Some T2 => Some (Ty_Prod T1 T2)
      | _, _ => None
      end
  | tm_fst t1 =>
      match typecheck Gamma t1 with
      | Some (Ty_Prod T1 _) => Some T1
      | _ => None
      end
  | tm_snd t1 =>
      match typecheck Gamma t1 with
      | Some (Ty_Prod _ T2) => Some T2
      | _ => None
      end
  | tm_unit => Some Ty_Unit
  end.

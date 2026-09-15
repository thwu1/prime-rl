(* Typing.v - SOLVED *)

Require Export Terms.
Require Import Coq.Strings.String.

Definition context := list (var * ty).

Fixpoint lookup (x : var) (Gamma : context) : option ty :=
  match Gamma with
  | nil => None
  | (y, T) :: rest => if String.eqb x y then Some T else lookup x rest
  end.

Inductive has_type : context -> tm -> ty -> Prop :=
  | T_Var : forall Gamma x T, lookup x Gamma = Some T -> has_type Gamma (tm_var x) T
  | T_Abs : forall Gamma x T1 T2 t, has_type ((x, T1) :: Gamma) t T2 -> has_type Gamma (tm_abs x T1 t) (Ty_Arrow T1 T2)
  | T_App : forall Gamma t1 t2 T1 T2, has_type Gamma t1 (Ty_Arrow T1 T2) -> has_type Gamma t2 T1 -> has_type Gamma (tm_app t1 t2) T2
  | T_Pair : forall Gamma t1 t2 T1 T2, has_type Gamma t1 T1 -> has_type Gamma t2 T2 -> has_type Gamma (tm_pair t1 t2) (Ty_Prod T1 T2)
  | T_Fst : forall Gamma t T1 T2, has_type Gamma t (Ty_Prod T1 T2) -> has_type Gamma (tm_fst t) T1
  | T_Snd : forall Gamma t T1 T2, has_type Gamma t (Ty_Prod T1 T2) -> has_type Gamma (tm_snd t) T2
  | T_Unit : forall Gamma, has_type Gamma tm_unit Ty_Unit
  | T_Sub : forall Gamma t S T, has_type Gamma t S -> S <: T -> has_type Gamma t T.

Hint Constructors has_type : core.

Lemma typing_inversion_abs : forall Gamma x S1 t2 T,
  has_type Gamma (tm_abs x S1 t2) T ->
  exists S2, has_type ((x, S1) :: Gamma) t2 S2 /\ (Ty_Arrow S1 S2) <: T.
Proof.
  intros Gamma x S1 t2 T Htyp. remember (tm_abs x S1 t2) as tabs.
  induction Htyp; try discriminate.
  - injection Heqtabs as ? ? ?. subst. exists T2. auto.
  - destruct (IHHtyp Heqtabs) as [S2 [Hbody Hsub]].
    exists S2. split; auto. eapply sub_trans; eassumption.
Qed.

Lemma canonical_forms_arrow : forall v T1 T2,
  has_type nil v (Ty_Arrow T1 T2) -> value v ->
  exists x S1 t, v = tm_abs x S1 t.
Proof.
  intros v T1 T2 Htyp Hval.
  remember (@nil (var * ty)) as Gamma. remember (Ty_Arrow T1 T2) as TT.
  revert T1 T2 HeqTT.
  induction Htyp; intros ? ? HeqTT; subst; try discriminate;
    try solve [inversion Hval].
  - injection HeqTT as ? ?. subst. eauto.
  - match goal with
    | [ Hsub : subtype _ _ |- _ ] =>
        apply sub_inversion_arrow in Hsub;
        destruct Hsub as [? [? [? [? ?]]]]; subst; eapply IHHtyp; eauto
    end.
Qed.

Lemma canonical_forms_prod : forall v T1 T2,
  has_type nil v (Ty_Prod T1 T2) -> value v ->
  exists v1 v2, v = tm_pair v1 v2 /\ value v1 /\ value v2.
Proof.
  intros v T1 T2 Htyp Hval.
  remember (@nil (var * ty)) as Gamma. remember (Ty_Prod T1 T2) as TT.
  revert T1 T2 HeqTT.
  induction Htyp; intros ? ? HeqTT; subst; try discriminate;
    try solve [inversion Hval].
  - injection HeqTT as ? ?. subst. inversion Hval; subst. eauto.
  - match goal with
    | [ Hsub : subtype _ _ |- _ ] =>
        apply sub_inversion_prod in Hsub;
        destruct Hsub as [? [? [? [? ?]]]]; subst; eapply IHHtyp; eauto
    end.
Qed.

Theorem progress : forall t T,
  has_type nil t T -> value t \/ exists t', t --> t'.
Proof.
  intros t T Htyp. remember (@nil (var * ty)) as Gamma.
  induction Htyp; subst.
  - discriminate.
  - left. constructor.
  - right.
    assert (IH1 : value t1 \/ (exists t', t1 --> t')) by auto.
    assert (IH2 : value t2 \/ (exists t', t2 --> t')) by auto.
    destruct IH1 as [Hval1 | [t1' Hstep1]].
    + destruct IH2 as [Hval2 | [t2' Hstep2]].
      * destruct (canonical_forms_arrow _ _ _ Htyp1 Hval1) as [x [S1 [t0 Heq]]]. subst. eauto.
      * eauto.
    + eauto.
  - assert (IH1 : value t1 \/ (exists t', t1 --> t')) by auto.
    assert (IH2 : value t2 \/ (exists t', t2 --> t')) by auto.
    destruct IH1 as [Hval1 | [t1' Hstep1]].
    + destruct IH2 as [Hval2 | [t2' Hstep2]].
      * left. auto.
      * right. eauto.
    + right. eauto.
  - right. assert (IH1 : value t \/ (exists t', t --> t')) by auto.
    destruct IH1 as [Hval | [t' Hstep]].
    + destruct (canonical_forms_prod _ _ _ Htyp Hval) as [v1 [v2 [Heq [Hv1 Hv2]]]]. subst. eauto.
    + eauto.
  - right. assert (IH1 : value t \/ (exists t', t --> t')) by auto.
    destruct IH1 as [Hval | [t' Hstep]].
    + destruct (canonical_forms_prod _ _ _ Htyp Hval) as [v1 [v2 [Heq [Hv1 Hv2]]]]. subst. eauto.
    + eauto.
  - left. constructor.
  - auto.
Qed.

Lemma weakening : forall Gamma Gamma' t T,
  (forall x U, lookup x Gamma = Some U -> lookup x Gamma' = Some U) ->
  has_type Gamma t T -> has_type Gamma' t T.
Proof.
  intros Gamma Gamma' t T Hsub Htyp. generalize dependent Gamma'.
  induction Htyp; intros Gamma'0 Hsub; eauto.
  - apply T_Abs. apply IHHtyp. intros y U Hy.
    unfold lookup in *. fold lookup in *. destruct (String.eqb y x) eqn:E; auto.
Qed.

Lemma substitution_preserves_typing : forall Gamma x U t v T,
  has_type ((x, U) :: Gamma) t T -> has_type nil v U ->
  has_type Gamma (subst x v t) T.
Proof.
  intros Gamma x U t. revert Gamma x U.
  induction t as [y | y Tann body IHbody | t1 IH1 t2 IH2 | t1 IH1 t2 IH2 | t1 IH1 | t1 IH1 | ];
    intros Gamma x0 U v0 T Htyp Hv; simpl.
  - destruct (String.eqb x0 y) eqn:E.
    + apply String.eqb_eq in E. subst.
      remember (tm_var y) as tv. remember ((y, U) :: Gamma) as G.
      induction Htyp; try discriminate.
      * injection Heqtv as ->. subst.
        unfold lookup in H. fold lookup in H. rewrite String.eqb_refl in H.
        injection H as ->. eapply weakening; [|eassumption]. intros. discriminate.
      * eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
    + remember (tm_var y) as tv. remember ((x0, U) :: Gamma) as G.
      induction Htyp; try discriminate.
      * injection Heqtv as ->. subst. apply T_Var.
        unfold lookup in H. fold lookup in H.
        rewrite (eqb_sym y x0) in H. rewrite E in H. exact H.
      * eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
  - destruct (String.eqb x0 y) eqn:E.
    + apply String.eqb_eq in E. subst.
      remember (tm_abs y Tann body) as tabs. remember ((y, U) :: Gamma) as G.
      induction Htyp; try discriminate.
      * injection Heqtabs as -> -> ->. subst. apply T_Abs.
        eapply weakening; [|eassumption].
        intros z Tz Hz. unfold lookup in *. fold lookup in *.
        destruct (String.eqb z y) eqn:E2; auto.
      * eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
    + remember (tm_abs y Tann body) as tabs. remember ((x0, U) :: Gamma) as G.
      induction Htyp; try discriminate.
      * injection Heqtabs as -> -> ->. subst. apply T_Abs.
        eapply IHbody with (U := U); auto.
        eapply weakening; [|eassumption].
        intros z Tz Hz. unfold lookup. fold lookup. unfold lookup in Hz. fold lookup in Hz.
        destruct (String.eqb z x0) eqn:E2; destruct (String.eqb z y) eqn:E3; auto.
        apply String.eqb_eq in E2. apply String.eqb_eq in E3. subst.
        rewrite String.eqb_refl in E. discriminate.
      * eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
  - remember (tm_app t1 t2) as tapp. remember ((x0, U) :: Gamma) as G.
    induction Htyp; try discriminate.
    + injection Heqtapp as -> ->. subst. eapply T_App; [eapply IH1|eapply IH2]; eauto.
    + eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
  - remember (tm_pair t1 t2) as tp. remember ((x0, U) :: Gamma) as G.
    induction Htyp; try discriminate.
    + injection Heqtp as -> ->. subst. eapply T_Pair; [eapply IH1|eapply IH2]; eauto.
    + eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
  - remember (tm_fst t1) as tf. remember ((x0, U) :: Gamma) as G.
    induction Htyp; try discriminate.
    + injection Heqtf as ->. subst. eapply T_Fst; eapply IH1; eauto.
    + eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
  - remember (tm_snd t1) as ts. remember ((x0, U) :: Gamma) as G.
    induction Htyp; try discriminate.
    + injection Heqts as ->. subst. eapply T_Snd; eapply IH1; eauto.
    + eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
  - remember tm_unit as tu. remember ((x0, U) :: Gamma) as G.
    induction Htyp; try discriminate.
    + subst. apply T_Unit.
    + eapply T_Sub. { eapply IHHtyp; eauto. } { assumption. }
Qed.

Lemma typing_inversion_app : forall Gamma t1 t2 T,
  has_type Gamma (tm_app t1 t2) T ->
  exists S1 S2, has_type Gamma t1 (Ty_Arrow S1 S2) /\ has_type Gamma t2 S1 /\ S2 <: T.
Proof.
  intros Gamma t1 t2 T Htyp. remember (tm_app t1 t2) as tapp.
  induction Htyp; try discriminate.
  - injection Heqtapp as ? ?. subst. exists T1, T2. auto.
  - destruct (IHHtyp Heqtapp) as [S1 [S2 [H1 [H2 H3]]]].
    exists S1, S2. repeat split; auto. eapply sub_trans; eassumption.
Qed.

Lemma typing_inversion_pair : forall Gamma t1 t2 T,
  has_type Gamma (tm_pair t1 t2) T ->
  exists S1 S2, has_type Gamma t1 S1 /\ has_type Gamma t2 S2 /\ (Ty_Prod S1 S2) <: T.
Proof.
  intros Gamma t1 t2 T Htyp. remember (tm_pair t1 t2) as tp.
  induction Htyp; try discriminate.
  - injection Heqtp as ? ?. subst. exists T1, T2. auto.
  - destruct (IHHtyp Heqtp) as [S1 [S2 [H1 [H2 H3]]]].
    exists S1, S2. repeat split; auto. eapply sub_trans; eassumption.
Qed.

Lemma typing_inversion_fst : forall Gamma t T,
  has_type Gamma (tm_fst t) T ->
  exists S1 S2, has_type Gamma t (Ty_Prod S1 S2) /\ S1 <: T.
Proof.
  intros Gamma t T Htyp. remember (tm_fst t) as tf.
  induction Htyp; try discriminate.
  - injection Heqtf as ?. subst. exists T1, T2. auto.
  - destruct (IHHtyp Heqtf) as [S1 [S2 [H1 H2]]].
    exists S1, S2. split; auto. eapply sub_trans; eassumption.
Qed.

Lemma typing_inversion_snd : forall Gamma t T,
  has_type Gamma (tm_snd t) T ->
  exists S1 S2, has_type Gamma t (Ty_Prod S1 S2) /\ S2 <: T.
Proof.
  intros Gamma t T Htyp. remember (tm_snd t) as ts.
  induction Htyp; try discriminate.
  - injection Heqts as ?. subst. exists T1, T2. auto.
  - destruct (IHHtyp Heqts) as [S1 [S2 [H1 H2]]].
    exists S1, S2. split; auto. eapply sub_trans; eassumption.
Qed.

Theorem preservation : forall t t' T,
  has_type nil t T -> t --> t' -> has_type nil t' T.
Proof.
  intros t t' T Htyp Hstep. generalize dependent T.
  induction Hstep; intros T Htyp.
  - apply typing_inversion_app in Htyp.
    destruct Htyp as [S1 [S2 [Hfun [Harg Hsub]]]].
    apply typing_inversion_abs in Hfun.
    destruct Hfun as [S3 [Hbody Hsub2]].
    apply sub_inversion_arrow in Hsub2.
    destruct Hsub2 as [U1 [U2 [Heq [Hcontra Hco]]]].
    injection Heq as ? ?. subst.
    eapply T_Sub; [| eapply sub_trans; [exact Hco | exact Hsub]].
    eapply substitution_preserves_typing; eauto.
  - apply typing_inversion_app in Htyp.
    destruct Htyp as [S1 [S2 [H1 [H2 H3]]]]. eapply T_Sub; [|exact H3]. eauto.
  - apply typing_inversion_app in Htyp.
    destruct Htyp as [S1 [S2 [H1 [H2 H3]]]]. eapply T_Sub; [|exact H3]. eauto.
  - apply typing_inversion_pair in Htyp.
    destruct Htyp as [S1 [S2 [H1 [H2 H3]]]]. eapply T_Sub; [|exact H3]. eauto.
  - apply typing_inversion_pair in Htyp.
    destruct Htyp as [S1 [S2 [H1 [H2 H3]]]]. eapply T_Sub; [|exact H3]. eauto.
  - apply typing_inversion_fst in Htyp.
    destruct Htyp as [S1 [S2 [H1 H2]]]. eapply T_Sub; [|exact H2]. eauto.
  - apply typing_inversion_fst in Htyp.
    destruct Htyp as [S1 [S2 [H1 H2]]].
    apply typing_inversion_pair in H1.
    destruct H1 as [U1 [U2 [H3 [H4 H5]]]].
    apply sub_inversion_prod in H5.
    destruct H5 as [W1 [W2 [Heq [Hs1 Hs2]]]].
    injection Heq as ? ?. subst.
    eapply T_Sub; [exact H3 | eapply sub_trans; [exact Hs1 | exact H2]].
  - apply typing_inversion_snd in Htyp.
    destruct Htyp as [S1 [S2 [H1 H2]]]. eapply T_Sub; [|exact H2]. eauto.
  - apply typing_inversion_snd in Htyp.
    destruct Htyp as [S1 [S2 [H1 H2]]].
    apply typing_inversion_pair in H1.
    destruct H1 as [U1 [U2 [H3 [H4 H5]]]].
    apply sub_inversion_prod in H5.
    destruct H5 as [W1 [W2 [Heq [Hs1 Hs2]]]].
    injection Heq as ? ?. subst.
    eapply T_Sub; [exact H4 | eapply sub_trans; [exact Hs2 | exact H2]].
Qed.

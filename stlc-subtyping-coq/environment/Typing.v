(* Typing.v - Typing relation with subtyping, progress and preservation *)

Require Export Terms.
Require Import Coq.Strings.String.

(** Typing context *)
Definition context := list (var * ty).

Fixpoint lookup (x : var) (Gamma : context) : option ty :=
  match Gamma with
  | nil => None
  | (y, T) :: rest => if String.eqb x y then Some T else lookup x rest
  end.

(** Typing relation *)

Inductive has_type : context -> tm -> ty -> Prop :=
  | T_Var : forall Gamma x T,
      lookup x Gamma = Some T ->
      has_type Gamma (tm_var x) T
  | T_Abs : forall Gamma x T1 T2 t,
      has_type ((x, T1) :: Gamma) t T2 ->
      has_type Gamma (tm_abs x T1 t) (Ty_Arrow T1 T2)
  | T_App : forall Gamma t1 t2 T1 T2,
      has_type Gamma t1 (Ty_Arrow T1 T2) ->
      has_type Gamma t2 T1 ->
      has_type Gamma (tm_app t1 t2) T2
  | T_Pair : forall Gamma t1 t2 T1 T2,
      has_type Gamma t1 T1 ->
      has_type Gamma t2 T2 ->
      has_type Gamma (tm_pair t1 t2) (Ty_Prod T1 T2)
  | T_Fst : forall Gamma t T1 T2,
      has_type Gamma t (Ty_Prod T1 T2) ->
      has_type Gamma (tm_fst t) T1
  | T_Snd : forall Gamma t T1 T2,
      has_type Gamma t (Ty_Prod T1 T2) ->
      has_type Gamma (tm_snd t) T2
  | T_Unit : forall Gamma,
      has_type Gamma tm_unit Ty_Unit
  | T_Sub : forall Gamma t S T,
      has_type Gamma t S ->
      S <: T ->
      has_type Gamma t T.

Hint Constructors has_type : core.

(** Typing inversion lemma for abstractions — needed for preservation.
    Prove by induction on the typing derivation. *)

Lemma typing_inversion_abs : forall Gamma x S1 t T,
  has_type Gamma (tm_abs x S1 t) T ->
  exists S2, has_type ((x, S1) :: Gamma) t S2 /\ (Ty_Arrow S1 S2) <: T.
Proof.
  (* FILL IN HERE *) Admitted.

(** Canonical forms lemmas *)

Lemma canonical_forms_arrow : forall v T1 T2,
  has_type nil v (Ty_Arrow T1 T2) ->
  value v ->
  exists x S1 t, v = tm_abs x S1 t.
Proof.
  (* FILL IN HERE *) Admitted.

Lemma canonical_forms_prod : forall v T1 T2,
  has_type nil v (Ty_Prod T1 T2) ->
  value v ->
  exists v1 v2, v = tm_pair v1 v2 /\ value v1 /\ value v2.
Proof.
  (* FILL IN HERE *) Admitted.

(** Progress *)

Theorem progress : forall t T,
  has_type nil t T ->
  value t \/ exists t', t --> t'.
Proof.
  (* FILL IN HERE *) Admitted.

(** Weakening — provided for use in substitution proof *)

Lemma weakening : forall Gamma Gamma' t T,
  (forall x U, lookup x Gamma = Some U -> lookup x Gamma' = Some U) ->
  has_type Gamma t T ->
  has_type Gamma' t T.
Proof.
  intros Gamma Gamma' t T Hsub Htyp.
  generalize dependent Gamma'.
  induction Htyp; intros Gamma'0 Hsub; eauto.
  - apply T_Abs. apply IHHtyp.
    intros y U Hy. unfold lookup in *. fold lookup in *.
    destruct (String.eqb y x) eqn:E; auto.
Qed.

(** Substitution preserves typing *)

Lemma substitution_preserves_typing : forall Gamma x U t v T,
  has_type ((x, U) :: Gamma) t T ->
  has_type nil v U ->
  has_type Gamma (subst x v t) T.
Proof.
  (* FILL IN HERE *) Admitted.

(** Preservation *)

Theorem preservation : forall t t' T,
  has_type nil t T ->
  t --> t' ->
  has_type nil t' T.
Proof.
  (* FILL IN HERE *) Admitted.

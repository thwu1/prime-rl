(* Terms.v - Term syntax and operational semantics *)

Require Export Subtyping.
Require Export List.
Import ListNotations.

Definition var := string.

Inductive tm : Type :=
  | tm_var   : var -> tm
  | tm_abs   : var -> ty -> tm -> tm
  | tm_app   : tm -> tm -> tm
  | tm_pair  : tm -> tm -> tm
  | tm_fst   : tm -> tm
  | tm_snd   : tm -> tm
  | tm_unit  : tm.

(** Values *)
Inductive value : tm -> Prop :=
  | v_abs : forall x T t,
      value (tm_abs x T t)
  | v_pair : forall v1 v2,
      value v1 -> value v2 ->
      value (tm_pair v1 v2)
  | v_unit :
      value tm_unit.

Hint Constructors value : core.

(** Substitution *)
Fixpoint subst (x : var) (s : tm) (t : tm) : tm :=
  match t with
  | tm_var y       => if String.eqb x y then s else t
  | tm_abs y T t1  => tm_abs y T (if String.eqb x y then t1 else subst x s t1)
  | tm_app t1 t2   => tm_app (subst x s t1) (subst x s t2)
  | tm_pair t1 t2  => tm_pair (subst x s t1) (subst x s t2)
  | tm_fst t1      => tm_fst (subst x s t1)
  | tm_snd t1      => tm_snd (subst x s t1)
  | tm_unit        => tm_unit
  end.

(** Small-step operational semantics *)
Reserved Notation "t '-->' t'" (at level 40).

Inductive step : tm -> tm -> Prop :=
  | ST_AppAbs : forall x T2 t1 v2,
      value v2 ->
      (tm_app (tm_abs x T2 t1) v2) --> (subst x v2 t1)
  | ST_App1 : forall t1 t1' t2,
      t1 --> t1' ->
      (tm_app t1 t2) --> (tm_app t1' t2)
  | ST_App2 : forall v1 t2 t2',
      value v1 ->
      t2 --> t2' ->
      (tm_app v1 t2) --> (tm_app v1 t2')
  | ST_Pair1 : forall t1 t1' t2,
      t1 --> t1' ->
      (tm_pair t1 t2) --> (tm_pair t1' t2)
  | ST_Pair2 : forall v1 t2 t2',
      value v1 ->
      t2 --> t2' ->
      (tm_pair v1 t2) --> (tm_pair v1 t2')
  | ST_Fst1 : forall t1 t1',
      t1 --> t1' ->
      (tm_fst t1) --> (tm_fst t1')
  | ST_FstPair : forall v1 v2,
      value v1 -> value v2 ->
      (tm_fst (tm_pair v1 v2)) --> v1
  | ST_Snd1 : forall t1 t1',
      t1 --> t1' ->
      (tm_snd t1) --> (tm_snd t1')
  | ST_SndPair : forall v1 v2,
      value v1 -> value v2 ->
      (tm_snd (tm_pair v1 v2)) --> v2

where "t '-->' t'" := (step t t').

Hint Constructors step : core.

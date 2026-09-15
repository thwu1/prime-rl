(* Algorithmic.v - Algorithmic type checking *)

Require Export Typing.
Require Import Coq.Bool.Bool.
Require Import Coq.Strings.String.

(** Decidability of subtyping — mutual recursion on S.

    [sub_dec S T] decides [S <: T].
    [sub_dec_rev S T] decides [T <: S].
    Both recurse structurally on S to satisfy the termination checker. *)
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

Lemma sub_dec_sound : forall S T,
  sub_dec S T = true -> S <: T.
Proof.
  (* FILL IN HERE *) Admitted.

Lemma sub_dec_complete : forall S T,
  S <: T -> sub_dec S T = true.
Proof.
  (* FILL IN HERE *) Admitted.

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
Proof.
  induction T; simpl; try rewrite IHT1; try rewrite IHT2; auto.
Qed.

Lemma ty_eqb_eq : forall T1 T2, ty_eqb T1 T2 = true -> T1 = T2.
Proof.
  induction T1; destruct T2; simpl; intros; try discriminate;
  try reflexivity;
  apply andb_true_iff in H; destruct H;
  f_equal; auto.
Qed.

(** Algorithmic type checker — implement this function.

    It should return [Some T] where T is the principal (most precise)
    type of [t] in context [Gamma], or [None] if the term is ill-typed.

    The function must be a [Fixpoint] that is structurally recursive
    on the term [t]. Use [sub_dec] for subtype checks in application. *)

Fixpoint typecheck (Gamma : context) (t : tm) : option ty :=
  (* FILL IN HERE *)
  None. (* placeholder — replace with real implementation *)

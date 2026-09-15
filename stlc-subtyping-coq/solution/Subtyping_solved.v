(* Subtyping.v - SOLVED *)

Require Export Types.

Reserved Notation "T '<:' U" (at level 40).

Inductive subtype : ty -> ty -> Prop :=
  | S_Refl : forall T,
      T <: T
  | S_Top : forall S,
      S <: Ty_Top
  | S_Arrow : forall S1 S2 T1 T2,
      T1 <: S1 ->
      S2 <: T2 ->
      (Ty_Arrow S1 S2) <: (Ty_Arrow T1 T2)
  | S_Prod : forall S1 S2 T1 T2,
      S1 <: T1 ->
      S2 <: T2 ->
      (Ty_Prod S1 S2) <: (Ty_Prod T1 T2)
where "T '<:' U" := (subtype T U).

Hint Constructors subtype : core.

Lemma sub_trans : forall S U T,
  S <: U -> U <: T -> S <: T.
Proof.
  intros S U. generalize dependent S.
  induction U; intros S T HSU HUT.
  - (* Ty_Top *)
    inversion HUT; subst; auto.
  - (* Ty_Arrow U1 U2 *)
    inversion HSU; subst.
    + exact HUT.
    + inversion HUT; subst.
      * apply S_Arrow; assumption.
      * constructor.
      * apply S_Arrow; [eapply IHU1 | eapply IHU2]; eassumption.
  - (* Ty_Prod U1 U2 *)
    inversion HSU; subst.
    + exact HUT.
    + inversion HUT; subst.
      * apply S_Prod; assumption.
      * constructor.
      * apply S_Prod; [eapply IHU1 | eapply IHU2]; eassumption.
  - (* Ty_Unit *)
    inversion HSU; subst. exact HUT.
Qed.

Lemma sub_inversion_arrow : forall U V1 V2,
  U <: Ty_Arrow V1 V2 ->
  exists U1 U2, U = Ty_Arrow U1 U2 /\ V1 <: U1 /\ U2 <: V2.
Proof.
  intros U V1 V2 H.
  inversion H; subst.
  - exists V1, V2. auto.
  - exists S1, S2. auto.
Qed.

Lemma sub_inversion_prod : forall U V1 V2,
  U <: Ty_Prod V1 V2 ->
  exists U1 U2, U = Ty_Prod U1 U2 /\ U1 <: V1 /\ U2 <: V2.
Proof.
  intros U V1 V2 H.
  inversion H; subst.
  - exists V1, V2. auto.
  - exists S1, S2. auto.
Qed.

Lemma sub_inversion_unit : forall U,
  U <: Ty_Unit ->
  U = Ty_Unit.
Proof.
  intros U H.
  inversion H; subst. reflexivity.
Qed.

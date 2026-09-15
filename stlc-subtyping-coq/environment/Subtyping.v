(* Subtyping.v - Subtyping relation for STLC *)

Require Export Types.

Reserved Notation "T '<:' U" (at level 40).

(** Declarative subtyping — S_Trans is NOT a constructor;
    it must be proved admissible from the structural rules. *)
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

(** Prove that subtyping is transitive. *)

Lemma sub_trans : forall S U T,
  S <: U -> U <: T -> S <: T.
Proof.
  (* FILL IN HERE *) Admitted.

(** Subtyping inversion lemmas *)

Lemma sub_inversion_arrow : forall U V1 V2,
  U <: Ty_Arrow V1 V2 ->
  exists U1 U2, U = Ty_Arrow U1 U2 /\ V1 <: U1 /\ U2 <: V2.
Proof.
  (* FILL IN HERE *) Admitted.

Lemma sub_inversion_prod : forall U V1 V2,
  U <: Ty_Prod V1 V2 ->
  exists U1 U2, U = Ty_Prod U1 U2 /\ U1 <: V1 /\ U2 <: V2.
Proof.
  (* FILL IN HERE *) Admitted.

Lemma sub_inversion_unit : forall U,
  U <: Ty_Unit ->
  U = Ty_Unit.
Proof.
  (* FILL IN HERE *) Admitted.


(* Modular feature flag registry.
   Provides a functor-based abstraction for configuration management. *)

Require Import Bool.

Module Type FLAG.
  Parameter is_set : bool.
End FLAG.

Module Enabled <: FLAG.
  Definition is_set := true.
End Enabled.

Module Disabled <: FLAG.
  Definition is_set := false.
End Disabled.

Module REGISTRY.

  Module Register (F : FLAG).

    Module State.
      Definition current := F.is_set.
      Definition flipped := negb F.is_set.
    End State.

    Module View := State.

  End Register.

End REGISTRY.

Include REGISTRY.

Module FlagA := Register Enabled.
Module FlagB := Register Disabled.

Definition a_current : bool := FlagA.View.current.
Definition b_current : bool := FlagB.View.current.
Definition a_flipped : bool := FlagA.View.flipped.
Definition b_flipped : bool := FlagB.View.flipped.

Lemma a_is_true : a_current = true.
Proof. reflexivity. Qed.

Lemma b_is_false : b_current = false.
Proof. reflexivity. Qed.

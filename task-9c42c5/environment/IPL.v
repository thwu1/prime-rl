
Require Import Ltac2.Ltac2.

Module IPLSolver.

  Import Ltac2.Control.

  Ltac2 Type exn ::= [ SearchFailed ].

  (** solve_prop depth: Depth-bounded proof search for intuitionistic
      propositional logic. Must handle /\, \/, ->, ~, <->, True, False.
      Must use Ltac2-native backtracking. Must fail on classically-valid
      but intuitionistically-invalid goals. *)
  Ltac2 rec solve_prop (depth : int) : unit :=
    Control.zero SearchFailed.

  Ltac2 ipl_auto () : unit := solve_prop 20.

End IPLSolver.

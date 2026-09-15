
From Ltac2 Require Import Ltac2.
From IPL Require Import IPL.
Import IPLSolver.

(* ============================================================ *)
(*  BASIC TESTS                                                  *)
(* ============================================================ *)

(* 1. Trivial *)
Goal True.
  ipl_auto ().
Qed.

(* 2. Identity *)
Goal forall A : Prop, A -> A.
  ipl_auto ().
Qed.

(* 3. Conjunction elimination left *)
Goal forall A B : Prop, A /\ B -> A.
  ipl_auto ().
Qed.

(* 4. Conjunction elimination right *)
Goal forall A B : Prop, A /\ B -> B.
  ipl_auto ().
Qed.

(* 5. Conjunction commutativity *)
Goal forall A B : Prop, A /\ B -> B /\ A.
  ipl_auto ().
Qed.

(* 6. Conjunction introduction *)
Goal forall A B : Prop, A -> B -> A /\ B.
  ipl_auto ().
Qed.

(* 7. Ex falso quodlibet *)
Goal forall A : Prop, False -> A.
  ipl_auto ().
Qed.

(* 8. Modus ponens *)
Goal forall A B : Prop, A -> (A -> B) -> B.
  ipl_auto ().
Qed.

(* ============================================================ *)
(*  MEDIUM TESTS                                                 *)
(* ============================================================ *)

(* 9. Disjunction elimination *)
Goal forall A B C : Prop, (A \/ B) -> (A -> C) -> (B -> C) -> C.
  ipl_auto ().
Qed.

(* 10. Disjunction introduction left *)
Goal forall A B : Prop, A -> A \/ B.
  ipl_auto ().
Qed.

(* 11. Disjunction introduction right *)
Goal forall A B : Prop, B -> A \/ B.
  ipl_auto ().
Qed.

(* 12. Distribution of conjunction over disjunction *)
Goal forall A B C : Prop, A /\ (B \/ C) -> (A /\ B) \/ (A /\ C).
  ipl_auto ().
Qed.

(* 13. Contrapositive *)
Goal forall A B : Prop, (A -> B) -> ~ B -> ~ A.
  ipl_auto ().
Qed.

(* 14. Non-contradiction *)
Goal forall A : Prop, ~ (A /\ ~ A).
  ipl_auto ().
Qed.

(* 15. De Morgan (intuitionistic: not-or to and-not) *)
Goal forall A B : Prop, ~ (A \/ B) -> ~ A /\ ~ B.
  ipl_auto ().
Qed.

(* 16. De Morgan (intuitionistic: and-not to not-or) *)
Goal forall A B : Prop, ~ A /\ ~ B -> ~ (A \/ B).
  ipl_auto ().
Qed.

(* ============================================================ *)
(*  HARD TESTS                                                   *)
(* ============================================================ *)

(* 17. Iff symmetry *)
Goal forall A B : Prop, (A <-> B) -> (B <-> A).
  ipl_auto ().
Qed.

(* 18. Iff transitivity *)
Goal forall A B C : Prop, (A <-> B) -> (B <-> C) -> (A <-> C).
  ipl_auto ().
Qed.

(* 19. Implication chain *)
Goal forall A B C D : Prop,
  (A -> B) -> (B -> C) -> (C -> D) -> A -> D.
  ipl_auto ().
Qed.

(* 20. Disjunction with forward reasoning *)
Goal forall A B C : Prop,
  (A \/ B) -> (A -> C) -> (B -> A) -> C.
  ipl_auto ().
Qed.

(* 21. Triple disjunction elimination *)
Goal forall A B C D : Prop,
  (A \/ B \/ C) -> (A -> D) -> (B -> D) -> (C -> D) -> D.
  ipl_auto ().
Qed.

(* 22. Conjunction in hypothesis applied to goal *)
Goal forall A B C : Prop,
  (A /\ B -> C) -> A -> B -> C.
  ipl_auto ().
Qed.

(* 23. Conjunction commutativity via iff *)
Goal forall A B : Prop,
  (A /\ B) <-> (B /\ A).
  ipl_auto ().
Qed.

(* 24. Currying equivalence *)
Goal forall A B C : Prop,
  (A /\ B -> C) <-> (A -> B -> C).
  ipl_auto ().
Qed.

(* 25. Weakening *)
Goal forall A B : Prop, A -> B -> A.
  ipl_auto ().
Qed.

(* 26. Double negation introduction *)
Goal forall A : Prop, A -> ~ ~ A.
  ipl_auto ().
Qed.

(* 27. Negation of False *)
Goal ~ False.
  ipl_auto ().
Qed.

(* ============================================================ *)
(*  NEGATIVE TESTS: classically valid, intuitionistically NOT    *)
(* ============================================================ *)

(* 28. Excluded middle — NOT intuitionistically valid *)
Goal forall A : Prop, A \/ ~ A.
  Fail ipl_auto ().
Abort.

(* 29. Double negation elimination — NOT intuitionistically valid *)
Goal forall A : Prop, ~ ~ A -> A.
  Fail ipl_auto ().
Abort.

(* 30. Peirce's law — NOT intuitionistically valid *)
Goal forall A B : Prop, ((A -> B) -> A) -> A.
  Fail ipl_auto ().
Abort.

(* ============================================================ *)
(*  DEPTH BOUND TESTS                                            *)
(* ============================================================ *)

(* 31. Long chain — solvable at depth 15 *)
Goal forall A B C D E F G : Prop,
  A -> (A -> B) -> (B -> C) -> (C -> D) -> (D -> E) -> (E -> F) -> (F -> G) -> G.
  solve_prop 15.
Qed.

(* 32. Same chain — must fail at depth 3 *)
Goal forall A B C D E F G : Prop,
  A -> (A -> B) -> (B -> C) -> (C -> D) -> (D -> E) -> (E -> F) -> (F -> G) -> G.
  Fail solve_prop 3.
Abort.

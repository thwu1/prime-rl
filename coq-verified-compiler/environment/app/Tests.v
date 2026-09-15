(* Tests.v - Computational correctness tests for the verified compiler.
   Each Example is checked by Coq's kernel via reflexivity,
   which forces actual computation of both sides. *)

Require Import List Arith.
Require Import Syntax Semantics StackMachine Compiler Optimizer.
Import ListNotations.

(* --- Evaluation tests --- *)

Example eval_plus : eval (Plus (Const 3) (Const 5)) = 8.
Proof. reflexivity. Qed.

Example eval_minus : eval (Minus (Const 10) (Const 3)) = 7.
Proof. reflexivity. Qed.

Example eval_times : eval (Times (Const 4) (Const 6)) = 24.
Proof. reflexivity. Qed.

Example eval_nested :
  eval (Plus (Times (Const 2) (Const 3))
             (Minus (Const 10) (Const 4))) = 12.
Proof. reflexivity. Qed.

(* --- Compilation + execution tests --- *)

Example compile_plus :
  exec (compile (Plus (Const 3) (Const 5))) [] = Some [8].
Proof. reflexivity. Qed.

Example compile_minus :
  exec (compile (Minus (Const 10) (Const 3))) [] = Some [7].
Proof. reflexivity. Qed.

Example compile_times :
  exec (compile (Times (Const 4) (Const 6))) [] = Some [24].
Proof. reflexivity. Qed.

Example compile_nested :
  exec (compile (Plus (Times (Const 2) (Const 3))
                      (Minus (Const 10) (Const 4)))) [] = Some [12].
Proof. reflexivity. Qed.

(* --- Optimizer tests --- *)

Example opt_plus : optimize (Plus (Const 3) (Const 5)) = Const 8.
Proof. reflexivity. Qed.

Example opt_minus : optimize (Minus (Const 10) (Const 3)) = Const 7.
Proof. reflexivity. Qed.

Example opt_nested :
  eval (optimize (Plus (Times (Const 2) (Const 3))
                       (Minus (Const 10) (Const 4)))) = 12.
Proof. reflexivity. Qed.

(* --- End-to-end: optimize then compile --- *)

Example e2e_test :
  exec (compile (optimize (Plus (Times (Const 2) (Const 3))
                                (Minus (Const 10) (Const 4))))) [] = Some [12].
Proof. reflexivity. Qed.

(* --- Main theorem: optimized compilation is correct --- *)

Theorem optimized_compile_correct : forall e s,
  exec (compile (optimize e)) s = Some (eval e :: s).
Proof.
  intros e s.
  rewrite compile_correct.
  rewrite optimize_correct.
  reflexivity.
Qed.

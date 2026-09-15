(* verify_tests.v - Independent verification tests.
   This file is compiled by the test harness against
   the agent's fixed code to verify correctness. *)

Require Import List Arith.
Require Import Syntax Semantics StackMachine Compiler Optimizer.
Import ListNotations.

(* Verify stack machine subtraction order *)
Example v_compile_minus :
  exec (compile (Minus (Const 10) (Const 3))) [] = Some [7].
Proof. reflexivity. Qed.

Example v_compile_minus2 :
  exec (compile (Minus (Const 3) (Const 10))) [] = Some [0].
Proof. reflexivity. Qed.

(* Verify compilation of all operators *)
Example v_compile_plus :
  exec (compile (Plus (Const 3) (Const 5))) [] = Some [8].
Proof. reflexivity. Qed.

Example v_compile_times :
  exec (compile (Times (Const 4) (Const 6))) [] = Some [24].
Proof. reflexivity. Qed.

Example v_compile_nested :
  exec (compile (Plus (Times (Const 2) (Const 3))
                      (Minus (Const 10) (Const 4)))) [] = Some [12].
Proof. reflexivity. Qed.

Example v_compile_deep :
  exec (compile (Minus (Times (Const 5) (Const 3))
                       (Plus (Const 2) (Const 5)))) [] = Some [8].
Proof. reflexivity. Qed.

(* Verify optimizer uses subtraction, not addition *)
Example v_opt_minus :
  optimize (Minus (Const 10) (Const 3)) = Const 7.
Proof. reflexivity. Qed.

Example v_opt_minus_trunc :
  optimize (Minus (Const 3) (Const 10)) = Const 0.
Proof. reflexivity. Qed.

Example v_opt_plus :
  optimize (Plus (Const 3) (Const 5)) = Const 8.
Proof. reflexivity. Qed.

Example v_opt_times :
  optimize (Times (Const 4) (Const 6)) = Const 24.
Proof. reflexivity. Qed.

(* Verify optimizer preserves semantics on nested expressions *)
Example v_opt_nested :
  eval (optimize (Plus (Times (Const 2) (Const 3))
                       (Minus (Const 10) (Const 4)))) = 12.
Proof. reflexivity. Qed.

(* End-to-end: optimize then compile *)
Example v_e2e :
  exec (compile (optimize (Minus (Times (Const 5) (Const 3))
                                 (Const 7)))) [] = Some [8].
Proof. reflexivity. Qed.

Example v_e2e2 :
  exec (compile (optimize (Plus (Minus (Const 100) (Const 42))
                                (Times (Const 3) (Const 7))))) [] = Some [79].
Proof. reflexivity. Qed.

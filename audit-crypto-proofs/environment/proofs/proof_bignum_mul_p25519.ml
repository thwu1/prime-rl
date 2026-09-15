(*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0 OR ISC OR MIT-0
 *)

(* ========================================================================= *)
(* Multiplication modulo p_25519, the field characteristic for curve25519.   *)
(* ========================================================================= *)

needs "x86/proofs/base.ml";;

(**** print_literal_from_elf "x86/curve25519/bignum_mul_p25519.o";;
 ****)

let bignum_mul_p25519_mc = define_assert_from_elf "bignum_mul_p25519_mc" "x86/curve25519/bignum_mul_p25519.o"
[
  0xf3; 0x0f; 0x1e; 0xfa;  (* ENDBR64 *)
  0x53;                    (* PUSH (% rbx) *)
  0x55;                    (* PUSH (% rbp) *)
  0x41; 0x54;              (* PUSH (% r12) *)
  0x41; 0x55;              (* PUSH (% r13) *)
  0x41; 0x56;              (* PUSH (% r14) *)
  0x41; 0x57;              (* PUSH (% r15) *)
  0x48; 0x89; 0xd1;        (* MOV (% rcx) (% rdx) *)
  0x31; 0xed;              (* XOR (% ebp) (% ebp) *)
  0x48; 0x8b; 0x11;        (* MOV (% rdx) (Memop Quadword (%% (rcx,0))) *)
  0xc4; 0x62; 0xbb; 0xf6; 0x0e;
                           (* MULX4 (% r9,% r8) (% rdx,Memop Quadword (%% (rsi,0))) *)
  0xc4; 0x62; 0xfb; 0xf6; 0x56; 0x08;
                           (* MULX4 (% r10,% rax) (% rdx,Memop Quadword (%% (rsi,8))) *)
  0x49; 0x01; 0xc1;        (* ADD (% r9) (% rax) *)
  0xc4; 0x62; 0xfb; 0xf6; 0x5e; 0x10;
                           (* MULX4 (% r11,% rax) (% rdx,Memop Quadword (%% (rsi,16))) *)
  0x49; 0x11; 0xc2;        (* ADC (% r10) (% rax) *)
  0xc4; 0x62; 0xfb; 0xf6; 0x66; 0x18;
                           (* MULX4 (% r12,% rax) (% rdx,Memop Quadword (%% (rsi,24))) *)
  0x49; 0x11; 0xc3;        (* ADC (% r11) (% rax) *)
  0x49; 0x11; 0xec          (* ADC (% r12) (% rbp) *)
  (* ... remaining machine code bytes omitted for brevity ... *)
];;

let bignum_mul_p25519_tmc = define_trimmed "bignum_mul_p25519_tmc" bignum_mul_p25519_mc;;

let BIGNUM_MUL_P25519_EXEC = X86_MK_EXEC_RULE bignum_mul_p25519_tmc;;

(* ------------------------------------------------------------------------- *)
(* Helpful lemmas and the prime definition.                                  *)
(* ------------------------------------------------------------------------- *)

let p_25519 = new_definition `p_25519 = 57896044618658097711785492504343953926634992332820282019728792003956564819949`;;

(* ------------------------------------------------------------------------- *)
(* Correctness of standard ABI version.                                      *)
(* ------------------------------------------------------------------------- *)

let BIGNUM_MUL_P25519_CORRECT = time prove
 (`!z x y m n pc.
        nonoverlapping (word pc,0x1c3) (z,8 * 4)
        ==> ensures x86
             (\s. bytes_loaded s (word pc) (BUTLAST bignum_mul_p25519_tmc) /\
                  read RIP s = word(pc + 0xa) /\
                  C_ARGUMENTS [z; x; y] s /\
                  bignum_from_memory (x,4) s = m /\
                  bignum_from_memory (y,4) s = n)
             (\s. read RIP s = word (pc + 0x1b8) /\
                  bignum_from_memory (z,4) s = (m * n) MOD (2 EXP 256))
         (MAYCHANGE [RIP; RAX; RBX; RCX; RDX; RBP;
                      R8; R9; R10; R11; R12; R13; R14; R15] ,,
           MAYCHANGE SOME_FLAGS ,, MAYCHANGE [events] ,,
           MAYCHANGE [memory :> bignum(z,4)])`,
  (* Proof body omitted for audit purposes *)
  CHEAT_TAC);;

let BIGNUM_MUL_P25519_SUBROUTINE_CORRECT = time prove
 (`!z x y m n pc stackpointer returnaddress.
        ALL (nonoverlapping (z,8 * 4))
            [(word pc,LENGTH bignum_mul_p25519_mc); (stackpointer,8)] /\
        nonoverlapping (word pc,LENGTH bignum_mul_p25519_mc) (stackpointer,8)
        ==> ensures x86
             (\s. bytes_loaded s (word pc) bignum_mul_p25519_mc /\
                  read RIP s = word pc /\
                  read RSP s = stackpointer /\
                  read (memory :> bytes64 stackpointer) s = returnaddress /\
                  C_ARGUMENTS [z; x; y] s /\
                  bignum_from_memory (x,4) s = m /\
                  bignum_from_memory (y,4) s = n)
             (\s. read RIP s = returnaddress /\
                  read RSP s = word_add stackpointer (word 8) /\
                  bignum_from_memory(z,4) s = (m * n) MOD (2 EXP 256))
           (MAYCHANGE [RSP] ,, MAYCHANGE_REGS_AND_FLAGS_PERMITTED_BY_ABI ,,
            MAYCHANGE [memory :> bignum(z,4)])`,
  CHEAT_TAC);;

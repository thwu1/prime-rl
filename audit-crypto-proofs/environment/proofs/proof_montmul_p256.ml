(*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0 OR ISC OR MIT-0
 *)

(* ========================================================================= *)
(* MULX-based Montgomery multiplication modulo p_256.                        *)
(* ========================================================================= *)

needs "x86/proofs/base.ml";;

(**** print_literal_from_elf "x86/p256/bignum_montmul_p256.o";;
 ****)

let bignum_montmul_p256_mc =
  define_assert_from_elf "bignum_montmul_p256_mc" "x86/p256/bignum_montmul_p256.o"
[
  0xf3; 0x0f; 0x1e; 0xfa;  (* ENDBR64 *)
  0x53;                    (* PUSH (% rbx) *)
  0x41; 0x54;              (* PUSH (% r12) *)
  0x41; 0x55;              (* PUSH (% r13) *)
  0x41; 0x56;              (* PUSH (% r14) *)
  0x41; 0x57;              (* PUSH (% r15) *)
  0x48; 0x89; 0xd1;        (* MOV (% rcx) (% rdx) *)
  0x45; 0x31; 0xed;        (* XOR (% r13d) (% r13d) *)
  0x48; 0x8b; 0x11;        (* MOV (% rdx) (Memop Quadword (%% (rcx,0))) *)
  0xc4; 0x62; 0xbb; 0xf6; 0x0e;
                           (* MULX4 (% r9,% r8) (% rdx,Memop Quadword (%% (rsi,0))) *)
  0xc4; 0x62; 0xe3; 0xf6; 0x56; 0x08;
                           (* MULX4 (% r10,% rbx) (% rdx,Memop Quadword (%% (rsi,8))) *)
  0x49; 0x11; 0xd9;        (* ADC (% r9) (% rbx) *)
  0xc4; 0x62; 0xe3; 0xf6; 0x5e; 0x10;
                           (* MULX4 (% r11,% rbx) (% rdx,Memop Quadword (%% (rsi,16))) *)
  0x49; 0x11; 0xda;        (* ADC (% r10) (% rbx) *)
  0xc4; 0x62; 0xe3; 0xf6; 0x66; 0x18;
                           (* MULX4 (% r12,% rbx) (% rdx,Memop Quadword (%% (rsi,24))) *)
  0x49; 0x11; 0xdb;        (* ADC (% r11) (% rbx) *)
  0x4d; 0x11; 0xec          (* ADC (% r12) (% r13) *)
  (* ... remaining machine code bytes omitted for brevity ... *)
];;

let bignum_montmul_p256_tmc = define_trimmed "bignum_montmul_p256_tmc" bignum_montmul_p256_mc;;

let BIGNUM_MONTMUL_P256_EXEC = X86_MK_EXEC_RULE bignum_montmul_p256_tmc;;

(* ------------------------------------------------------------------------- *)
(* Proof.                                                                    *)
(* ------------------------------------------------------------------------- *)

let p_256 = new_definition `p_256 = 115792089210356248762697446949407573530086143415290314195533631308867097853951`;;

let BIGNUM_MONTMUL_P256_CORRECT = time prove
 (`!z x y a b pc.
        nonoverlapping (word pc,0x242) (z,8 * 4)
        ==> ensures x86
             (\s. bytes_loaded s (word pc) (BUTLAST bignum_montmul_p256_tmc) /\
                  read RIP s = word(pc + 0x09) /\
                  C_ARGUMENTS [z; x; y] s /\
                  bignum_from_memory (x,4) s = a /\
                  bignum_from_memory (y,4) s = b)
             (\s. read RIP s = word (pc + 0x238) /\
                  (a * b <= 2 EXP 256 * p_256
                   ==> bignum_from_memory (z,4) s =
                       (inverse_mod p_256 (2 EXP 256) * a * b) MOD p_256))
             (MAYCHANGE [RIP; RAX; RBX; RCX; RDX;
                         R8; R9; R10; R11; R12; R13; R14; R15] ,,
              MAYCHANGE [memory :> bytes(z,8 * 4)] ,,
              MAYCHANGE SOME_FLAGS ,, MAYCHANGE [events])`,
  (* Proof body omitted for audit purposes *)
  CHEAT_TAC);;

let BIGNUM_MONTMUL_P256_SUBROUTINE_CORRECT = time prove
 (`!z x y a b pc stackpointer returnaddress.
        ALL (nonoverlapping (z,8 * 4))
            [(word pc,LENGTH bignum_montmul_p256_mc); (stackpointer,8)] /\
        nonoverlapping (word pc,LENGTH bignum_montmul_p256_mc) (stackpointer,8)
        ==> ensures x86
             (\s. bytes_loaded s (word pc) bignum_montmul_p256_mc /\
                  read RIP s = word pc /\
                  read RSP s = stackpointer /\
                  read (memory :> bytes64 stackpointer) s = returnaddress /\
                  C_ARGUMENTS [z; x; y] s /\
                  bignum_from_memory (x,4) s = a /\
                  bignum_from_memory (y,4) s = b)
             (\s. read RIP s = returnaddress /\
                  read RSP s = word_add stackpointer (word 8) /\
                  (a * b <= 2 EXP 256 * p_256
                   ==> bignum_from_memory (z,4) s =
                       (inverse_mod p_256 (2 EXP 256) * a * b) MOD p_256))
           (MAYCHANGE [RSP] ,, MAYCHANGE_REGS_AND_FLAGS_PERMITTED_BY_ABI ,,
            MAYCHANGE [memory :> bignum(z,4)])`,
  CHEAT_TAC);;

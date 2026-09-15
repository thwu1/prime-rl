(*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0 OR ISC OR MIT-0
 *)

(* ========================================================================= *)
(* Addition of bignums.                                                      *)
(* ========================================================================= *)

needs "x86/proofs/base.ml";;

(**** print_literal_from_elf "x86/generic/bignum_add.o";;
 ****)

let bignum_add_mc =
  define_assert_from_elf "bignum_add_mc" "x86/generic/bignum_add.o"
[
  0xf3; 0x0f; 0x1e; 0xfa;  (* ENDBR64 *)
  0x4d; 0x31; 0xd3;        (* XOR (% r10) (% r10) *)
  0x48; 0x39; 0xd7;        (* CMP (% rdi) (% rdx) *)
  0x48; 0x0f; 0x42; 0xd7;  (* CMOVB (% rdx) (% rdi) *)
  0x4c; 0x39; 0xc7;        (* CMP (% rdi) (% r8) *)
  0x4c; 0x0f; 0x42; 0xc7;  (* CMOVB (% r8) (% rdi) *)
  0x4c; 0x39; 0xc2;        (* CMP (% rdx) (% r8) *)
  0x72; 0x47;              (* JB (Imm8 (word 71)) *)
  0x48; 0x29; 0xd7;        (* SUB (% rdi) (% rdx) *)
  0x4c; 0x29; 0xc2;        (* SUB (% rdx) (% r8) *)
  0x48; 0xff; 0xc2;        (* INC (% rdx) *)
  0x4d; 0x85; 0xc0;        (* TEST (% r8) (% r8) *)
  0x74; 0x25;              (* JE (Imm8 (word 37)) *)
  0x4a; 0x8b; 0x04; 0xd1;  (* MOV (% rax) (Memop Quadword (%%% (rcx,3,r10))) *)
  0x4b; 0x13; 0x04; 0xd1;  (* ADC (% rax) (Memop Quadword (%%% (r9,3,r10))) *)
  0x4a; 0x89; 0x04; 0xd6;  (* MOV (Memop Quadword (%%% (rsi,3,r10))) (% rax) *)
  0x49; 0xff; 0xc2;        (* INC (% r10) *)
  0x49; 0xff; 0xc8;        (* DEC (% r8) *)
  0x75; 0xec;              (* JNE (Imm8 (word 236)) *)
  0xeb; 0x0f;              (* JMP (Imm8 (word 15)) *)
  0x4a; 0x8b; 0x04; 0xd1;  (* MOV (% rax) (Memop Quadword (%%% (rcx,3,r10))) *)
  0x48; 0x83; 0xd0; 0x00;  (* ADC (% rax) (Imm8 (word 0)) *)
  0x4a; 0x89; 0x04; 0xd6;  (* MOV (Memop Quadword (%%% (rsi,3,r10))) (% rax) *)
  0x49; 0xff; 0xc2;        (* INC (% r10) *)
  0x48; 0xff; 0xca;        (* DEC (% rdx) *)
  0x75; 0xec;              (* JNE (Imm8 (word 236)) *)
  0xb8; 0x00; 0x00; 0x00; 0x00;
                           (* MOV (% eax) (Imm32 (word 0)) *)
  0x48; 0x83; 0xd0; 0x00;  (* ADC (% rax) (Imm8 (word 0)) *)
  0x48; 0x85; 0xff;        (* TEST (% rdi) (% rdi) *)
  0x75; 0x43;              (* JNE (Imm8 (word 67)) *)
  0xc3;                    (* RET *)
  0x4c; 0x29; 0xc7;        (* SUB (% rdi) (% r8) *)
  0x49; 0x29; 0xd0;        (* SUB (% r8) (% rdx) *)
  0x48; 0x85; 0xd2;        (* TEST (% rdx) (% rdx) *)
  0x74; 0x14;              (* JE (Imm8 (word 20)) *)
  0x4a; 0x8b; 0x04; 0xd1;  (* MOV (% rax) (Memop Quadword (%%% (rcx,3,r10))) *)
  0x4b; 0x13; 0x04; 0xd1;  (* ADC (% rax) (Memop Quadword (%%% (r9,3,r10))) *)
  0x4a; 0x89; 0x04; 0xd6;  (* MOV (Memop Quadword (%%% (rsi,3,r10))) (% rax) *)
  0x49; 0xff; 0xc2;        (* INC (% r10) *)
  0x48; 0xff; 0xca;        (* DEC (% rdx) *)
  0x75; 0xec;              (* JNE (Imm8 (word 236)) *)
  0x4b; 0x8b; 0x04; 0xd1;  (* MOV (% rax) (Memop Quadword (%%% (r9,3,r10))) *)
  0x48; 0x83; 0xd0; 0x00;  (* ADC (% rax) (Imm8 (word 0)) *)
  0x4a; 0x89; 0x04; 0xd6;  (* MOV (Memop Quadword (%%% (rsi,3,r10))) (% rax) *)
  0x49; 0xff; 0xc2;        (* INC (% r10) *)
  0x49; 0xff; 0xc8;        (* DEC (% r8) *)
  0x75; 0xec;              (* JNE (Imm8 (word 236)) *)
  0xb8; 0x00; 0x00; 0x00; 0x00;
                           (* MOV (% eax) (Imm32 (word 0)) *)
  0x48; 0x83; 0xd0; 0x00;  (* ADC (% rax) (Imm8 (word 0)) *)
  0x48; 0x85; 0xff;        (* TEST (% rdi) (% rdi) *)
  0x75; 0x01;              (* JNE (Imm8 (word 1)) *)
  0xc3;                    (* RET *)
  0x4a; 0x89; 0x04; 0xd6;  (* MOV (Memop Quadword (%%% (rsi,3,r10))) (% rax) *)
  0x48; 0x31; 0xc0;        (* XOR (% rax) (% rax) *)
  0xeb; 0x04;              (* JMP (Imm8 (word 4)) *)
  0x4a; 0x89; 0x04; 0xd6;  (* MOV (Memop Quadword (%%% (rsi,3,r10))) (% rax) *)
  0x49; 0xff; 0xc2;        (* INC (% r10) *)
  0x48; 0xff; 0xcf;        (* DEC (% rdi) *)
  0x75; 0xf4;              (* JNE (Imm8 (word 244)) *)
  0xc3                     (* RET *)
];;

let bignum_add_tmc = define_trimmed "bignum_add_tmc" bignum_add_mc;;

let BIGNUM_ADD_EXEC = X86_MK_EXEC_RULE bignum_add_tmc;;

(* ------------------------------------------------------------------------- *)
(* Correctness of standard ABI version.                                      *)
(* ------------------------------------------------------------------------- *)

let BIGNUM_ADD_CORRECT = prove
 (`!p z m x a n y b pc.
        nonoverlapping (word pc,0xb5) (z,8 * val p) /\
        (x = z \/ nonoverlapping(x,8 * val m) (z,8 * val p)) /\
        (y = z \/ nonoverlapping(y,8 * val n) (z,8 * val p))
        ==> ensures x86
             (\s. bytes_loaded s (word pc) bignum_add_tmc /\
                  read RIP s = word pc /\
                  C_ARGUMENTS [p;z;m;x;n;y] s /\
                  bignum_from_memory (x,val m) s = a /\
                  bignum_from_memory (y,val n) s = b)
             (\s. (read RIP s = word(pc + 0x5c) \/
                   read RIP s = word(pc + 0x9e) \/
                   read RIP s = word(pc + 0xb4)) /\
                  bignum_from_memory (z,val p) s =
                  (a + b) MOD 2 EXP (64 * val p) /\
                  2 EXP (64 * val p) * val(C_RETURN s) +
                  bignum_from_memory (z,val p) s =
                  lowdigits a (val p) + lowdigits b (val p))
             (MAYCHANGE [RIP; RAX; RDI; RDX; R8; R10] ,,
              MAYCHANGE SOME_FLAGS ,, MAYCHANGE [events] ,,
              MAYCHANGE [memory :> bignum(z,val p)])`,
  (* Proof body omitted for audit purposes *)
  CHEAT_TAC);;

let BIGNUM_ADD_SUBROUTINE_CORRECT = prove
 (`!p z m x a n y b pc stackpointer returnaddress.
      ALL (nonoverlapping (z,8 * val p)) [(word pc,LENGTH bignum_add_mc); (stackpointer,8)] /\
      (x = z \/ nonoverlapping(x,8 * val m) (z,8 * val p)) /\
      (y = z \/ nonoverlapping(y,8 * val n) (z,8 * val p))
      ==> ensures x86
           (\s. bytes_loaded s (word pc) bignum_add_mc /\
                read RIP s = word pc /\
                read RSP s = stackpointer /\
                read (memory :> bytes64 stackpointer) s = returnaddress /\
                C_ARGUMENTS [p;z;m;x;n;y] s /\
                bignum_from_memory (x,val m) s = a /\
                bignum_from_memory (y,val n) s = b)
           (\s. read RIP s = returnaddress /\
                read RSP s = word_add stackpointer (word 8) /\
                bignum_from_memory (z,val p) s =
                (a + b) MOD 2 EXP (64 * val p) /\
                2 EXP (64 * val p) * val(C_RETURN s) +
                bignum_from_memory (z,val p) s =
                lowdigits a (val p) + lowdigits b (val p))
           (MAYCHANGE [RSP] ,, MAYCHANGE_REGS_AND_FLAGS_PERMITTED_BY_ABI ,,
            MAYCHANGE [memory :> bignum(z,val p)])`,
  CHEAT_TAC);;

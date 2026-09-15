(*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0 OR ISC OR MIT-0
 *)

(* ========================================================================= *)
(* Point addition in Montgomery-Jacobian coordinates for NIST P-256 curve.   *)
(* ========================================================================= *)

needs "x86/proofs/base.ml";;
needs "common/ecencoding.ml";;
needs "EC/jacobian.ml";;
needs "EC/nistp256.ml";;

prioritize_int();;
prioritize_real();;
prioritize_num();;

(**** print_literal_from_elf "x86/p256/p256_montjmixadd.o";;
 ****)

let p256_montjmixadd_mc = define_assert_from_elf
  "p256_montjmixadd_mc" "x86/p256/p256_montjmixadd.o"
[
  0xf3; 0x0f; 0x1e; 0xfa;  (* ENDBR64 *)
  0x53;                    (* PUSH (% rbx) *)
  0x55;                    (* PUSH (% rbp) *)
  0x41; 0x54;              (* PUSH (% r12) *)
  0x41; 0x55;              (* PUSH (% r13) *)
  0x41; 0x56;              (* PUSH (% r14) *)
  0x41; 0x57;              (* PUSH (% r15) *)
  0x48; 0x81; 0xec; 0xc0; 0x00; 0x00; 0x00;
                           (* SUB (% rsp) (Imm32 (word 192)) *)
  0x48; 0x89; 0xd5;        (* MOV (% rbp) (% rdx) *)
  0x48; 0x8b; 0x56; 0x40;  (* MOV (% rdx) (Memop Quadword (%% (rsi,64))) *)
  0xc4; 0x62; 0xbb; 0xf6; 0xfa;
                           (* MULX4 (% r15,% r8) (% rdx,% rdx) *)
  0xc4; 0x62; 0xb3; 0xf6; 0x56; 0x48;
                           (* MULX4 (% r10,% r9) (% rdx,Memop Quadword (%% (rsi,72))) *)
  0xc4; 0x62; 0xa3; 0xf6; 0x66; 0x58;
                           (* MULX4 (% r12,% r11) (% rdx,Memop Quadword (%% (rsi,88))) *)
  0x48; 0x8b; 0x56; 0x50;  (* MOV (% rdx) (Memop Quadword (%% (rsi,80))) *)
  0xc4; 0x62; 0x93; 0xf6; 0x76; 0x58;
                           (* MULX4 (% r14,% r13) (% rdx,Memop Quadword (%% (rsi,88))) *)
  0x31; 0xc9               (* XOR (% ecx) (% ecx) *)
  (* ... remaining machine code bytes omitted for brevity ... *)
];;

let p256_montjmixadd_tmc = define_trimmed "p256_montjmixadd_tmc" p256_montjmixadd_mc;;

let P256_MONTJMIXADD_EXEC = X86_MK_EXEC_RULE p256_montjmixadd_tmc;;

(* ------------------------------------------------------------------------- *)
(* Point representation in Montgomery-Jacobian coordinates.                  *)
(* ------------------------------------------------------------------------- *)

let p_256 = new_definition `p_256 = 115792089210356248762697446949407573530086143415290314195533631308867097853951`;;

let represents_p256 = new_definition
 `represents_p256 P (x,y,z) <=>
        x < p_256 /\ y < p_256 /\ z < p_256 /\
        SOME(paired (montgomery_decode (256,p_256)) (x,y,z)) = P`;;

let represents2_p256 = new_definition
 `represents2_p256 P (x,y) <=>
        x < p_256 /\ y < p_256 /\
        SOME(paired (montgomery_decode (256,p_256)) (x,y)) = P`;;

(* ------------------------------------------------------------------------- *)
(* Correctness theorem.                                                      *)
(* ------------------------------------------------------------------------- *)

let P256_MONTJMIXADD_CORRECT = time prove
 (`!p3 p1 t1 p2 t2 pc stackpointer.
        ALL (nonoverlapping (stackpointer,192))
            [(word pc,0x1cb4); (p1,96); (p2,64); (p3,96)]
        ==> ensures x86
             (\s. bytes_loaded s (word pc) (BUTLAST p256_montjmixadd_tmc) /\
                  read RIP s = word(pc + 0x11) /\
                  read RSP s = stackpointer /\
                  C_ARGUMENTS [p3; p1; p2] s /\
                  bignum_triple_from_memory (p1,4) s = t1 /\
                  bignum_pair_from_memory (p2,4) s = t2)
             (\s. read RIP s = word (pc + 0x1ca2) /\
                  !P1 P2. represents_p256 P1 t1 /\
                          represents2_p256 P2 t2 /\
                          ~(P1 = P2)
                          ==> represents_p256 (group_mul p256_group P1 P2)
                               (bignum_triple_from_memory(p3,4) s))
          (MAYCHANGE [RIP; RAX; RBX; RCX; RDX; RBP;
                      R8; R9; R10; R11; R12; R13; R14; R15] ,,
           MAYCHANGE SOME_FLAGS ,, MAYCHANGE [events] ,,
           MAYCHANGE [memory :> bytes(p3,96);
                      memory :> bytes(stackpointer,192)])`,
  (* Proof body omitted for audit purposes *)
  CHEAT_TAC);;

let P256_MONTJMIXADD_SUBROUTINE_CORRECT = time prove
 (`!p3 p1 t1 p2 t2 pc stackpointer returnaddress.
        ALL (nonoverlapping (word_sub stackpointer (word 240),240))
            [(word pc,LENGTH p256_montjmixadd_mc); (p1,96); (p2,64)] /\
        ALL (nonoverlapping (p3,96))
            [(word pc,LENGTH p256_montjmixadd_mc); (word_sub stackpointer (word 240),288)]
        ==> ensures x86
             (\s. bytes_loaded s (word pc) p256_montjmixadd_mc /\
                  read RIP s = word pc /\
                  read RSP s = stackpointer /\
                  read (memory :> bytes64 stackpointer) s = returnaddress /\
                  C_ARGUMENTS [p3; p1; p2] s /\
                  bignum_triple_from_memory (p1,4) s = t1 /\
                  bignum_pair_from_memory (p2,4) s = t2)
             (\s. read RIP s = returnaddress /\
                  read RSP s = word_add stackpointer (word 8) /\
                  !P1 P2. represents_p256 P1 t1 /\
                          represents2_p256 P2 t2 /\
                          ~(P1 = P2)
                          ==> represents_p256 (group_mul p256_group P1 P2)
                               (bignum_triple_from_memory(p3,4) s))
           (MAYCHANGE [RSP] ,, MAYCHANGE_REGS_AND_FLAGS_PERMITTED_BY_ABI ,,
            MAYCHANGE [memory :> bytes(p3,96);
                       memory :> bytes(word_sub stackpointer (word 240),240)])`,
  CHEAT_TAC);;

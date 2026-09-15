(* ================================================================== *)
(* Formal specification: P-256 Montgomery multiplication               *)
(* Excerpted from s2n-bignum bignum_montmul_p256 proof                 *)
(* ================================================================== *)

let p_256 = new_definition
  `p_256 = 115792089210356248762697446949407573530086143415290314195533631308867097853951`;;

(* Equivalently: p_256 = 2 EXP 256 - 2 EXP 224 + 2 EXP 192 + 2 EXP 96 - 1 *)

(* In 64-bit limbs (little-endian):
   p_256 = [0xFFFFFFFFFFFFFFFF; 0x00000000FFFFFFFF;
            0x0000000000000000; 0xFFFFFFFF00000001] *)

(* ------------------------------------------------------------------ *)
(* The Hoare triple for bignum_montmul_p256:                           *)
(*                                                                     *)
(* ensures x86                                                         *)
(*   (\s. // Preconditions:                                            *)
(*        read RDI s = z /\  read RSI s = x /\  read RDX s = y /\     *)
(*        bignum_from_memory(x,4) s = a /\                             *)
(*        bignum_from_memory(y,4) s = b /\                             *)
(*        a < p_256 /\ b < p_256 /\                                    *)
(*        (x = z \/ nonoverlapping(x,32)(z,32)) /\                     *)
(*        (y = z \/ nonoverlapping(y,32)(z,32)))                       *)
(*   (\s. // Postcondition:                                            *)
(*        bignum_from_memory(z,4) s =                                  *)
(*          (inverse_mod p_256 (2 EXP 256) * a * b) MOD p_256)         *)
(*   (MAYCHANGE [memory :> bytes(z,32)] ,,                             *)
(*    MAYCHANGE_REGS_AND_FLAGS_PERMITTED_BY_ABI)                       *)
(*                                                                     *)
(* ------------------------------------------------------------------ *)
(* Reading the postcondition:                                          *)
(*   The 4-word output at z equals:                                    *)
(*     (R^{-1} * a * b) mod p_256                                     *)
(*   where R = 2^256 and R^{-1} = inverse_mod p_256 (2 EXP 256).      *)
(*                                                                     *)
(* This is the standard Montgomery multiplication definition:          *)
(*   MontMul(a, b) = a * b * R^{-1} mod p                             *)
(*                                                                     *)
(* The precondition requires both inputs to be fully reduced (< p_256) *)
(* and allows z to alias either x or y (but x and y aliasing each     *)
(* other is implicitly allowed since both can equal z).                *)
(* ------------------------------------------------------------------ *)

(* Key mathematical properties used in the proof:

   1. Montgomery reduction constant:
      Let n0' = (-p_256^{-1}) mod 2^64.
      For P-256: n0' = 1, because p_256 mod 2^64 = 2^64 - 1,
      so p_256^{-1} mod 2^64 = 2^64 - 1, and -p_256^{-1} mod 2^64 = 1.

   2. The proof uses the CIOS (Coarsely Integrated Operand Scanning)
      approach: interleaved multiplication and reduction steps.
      Each iteration i computes:
        T := T + a[i] * b           (multiply-accumulate)
        m := T[0] * n0' mod 2^64   (reduction quotient)
        T := (T + m * p) >> 64     (reduce and shift)

   3. Loop invariant (after iteration i):
        T ≡ a[0..i] * b * 2^{-64*(i+1)} (mod p_256)
        T < p_256 + b

   4. After 4 iterations:
        T = a * b * R^{-1} mod p_256  (possibly + p_256)
      A single conditional subtraction yields the fully reduced result.

   5. The proof establishes T < 2 * p_256 after the loop, so at most
      one subtraction suffices.
*)

(* ------------------------------------------------------------------ *)
(* Montgomery squaring specification (bignum_montsqr_p256):            *)
(*                                                                     *)
(* Postcondition:                                                      *)
(*   bignum_from_memory(z,4) s =                                      *)
(*     (inverse_mod p_256 (2 EXP 256) * a * a) MOD p_256              *)
(*                                                                     *)
(* Same as montmul with b = a. May be optimized to exploit symmetry    *)
(* in the product (upper triangle doubling), but mathematically        *)
(* equivalent.                                                         *)
(* ------------------------------------------------------------------ *)

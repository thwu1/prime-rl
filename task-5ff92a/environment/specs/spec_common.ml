(* ================================================================== *)
(* Common bignum definitions from s2n-bignum HOL Light formalization   *)
(* These define the mathematical semantics of multi-precision integers *)
(* ================================================================== *)

(* A "bigdigit" extracts the i-th 64-bit word from an integer n *)
let bigdigit = new_definition
  `bigdigit n i = (n DIV (2 EXP (64 * i))) MOD (2 EXP 64)`;;

(* lowdigits n i gives the value of the bottom i digits (i*64 bits) *)
let lowdigits = new_definition
  `lowdigits n i = n MOD (2 EXP (64 * i))`;;

(* highdigits n i gives the value above the i-th digit boundary *)
let highdigits = new_definition
  `highdigits n i = n DIV (2 EXP (64 * i))`;;

(* Fundamental splitting lemma:
   2 EXP (64 * i) * highdigits n i + lowdigits n i = n
   This lets us reason about partial computations on prefixes/suffixes
   of a multi-precision integer. *)

(* bignum_from_memory(a,k) s reconstructs a k-digit integer from
   k consecutive 64-bit words at address a in state s, little-endian.
   Formally:
     bignum_from_memory(a,k) s =
       nsum {i | i < k}
            (\i. 2 EXP (64 * i) *
                 val(read (memory :> bytes64(word_add a (word(8 * i)))) s))

   So for a 4-digit (256-bit) number stored at address z:
     bignum_from_memory(z,4) s =
       val(word_at(z))          +
       val(word_at(z+8))  * 2^64  +
       val(word_at(z+16)) * 2^128 +
       val(word_at(z+24)) * 2^192
*)

(* Memory nonoverlapping condition:
   nonoverlapping (a, m) (b, n) means the m bytes at a and n bytes at b
   do not overlap. Used in preconditions to specify aliasing constraints.

   For P-256 operations on 4-word (32-byte) buffers:
     nonoverlapping (x, 32) (z, 32) OR x = z
   This allows either complete separation or complete aliasing (in-place). *)

(* MAYCHANGE lists specify the frame condition: exactly which parts of
   the machine state may be modified by the function. Everything else
   is preserved. Example:
     MAYCHANGE [memory :> bytes(z,32)]
   means only the 32 bytes at z may change in memory. *)

(* val : 64-bit word -> natural number
   Coerces a machine word to its unsigned integer value in [0, 2^64). *)

(* inverse_mod p n is the modular inverse of n modulo p, satisfying:
   (inverse_mod p n * n) MOD p = if coprime(n,p) then 1 else 0
   Used in Montgomery multiplication specifications where R^{-1} mod p
   appears in postconditions. *)

(** Extended conversions for three-limb 64-bit integers. *)

(** Convert to IEEE 754 double. Must match [Int64.to_float]. *)
val to_float : Triint64.t -> float

(** Convert from IEEE 754 double (truncation toward zero).
    Must match [Int64.of_float]. *)
val of_float : float -> Triint64.t

(** Convert to signed 32-bit integer (truncation).
    Must match [Int64.to_int32]. *)
val to_int32 : Triint64.t -> int32

(** Convert from signed 32-bit integer (sign-extends).
    Must match [Int64.of_int32]. *)
val of_int32 : int32 -> Triint64.t

(** Format as unsigned decimal string.
    For example, [Triint64.of_native (-1L)] should produce
    ["18446744073709551615"]. *)
val unsigned_to_string : Triint64.t -> string

(** Population count: number of 1-bits in the 64-bit representation. *)
val popcount : Triint64.t -> int

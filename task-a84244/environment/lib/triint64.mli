(** Three-limb 64-bit signed integer arithmetic.

    Values are stored as three limbs:
    - [lo]: bits 0..23   (24 bits, unsigned)
    - [mi]: bits 24..47  (24 bits, unsigned)
    - [hi]: bits 48..63  (16 bits, unsigned storage, sign in bit 15)

    The represented value is [hi * 2^48 + mi * 2^24 + lo], interpreted
    as a signed 64-bit two's complement integer. *)

type t

val of_native : Int64.t -> t
val to_native : t -> Int64.t

val zero : t
val one : t
val minus_one : t
val min_int : t
val max_int : t

val add : t -> t -> t
val sub : t -> t -> t
val mul : t -> t -> t
val div : t -> t -> t
val modulo : t -> t -> t
val neg : t -> t

val logand : t -> t -> t
val logor : t -> t -> t
val logxor : t -> t -> t

val shift_left : t -> int -> t
val shift_right : t -> int -> t
val shift_right_logical : t -> int -> t

val compare : t -> t -> int
val equal : t -> t -> bool

val to_string : t -> string
val of_string : string -> t
val to_hex : t -> string

val hash : t -> int

val marshal : t -> bytes
val unmarshal : bytes -> t

val is_zero : t -> bool
val is_neg : t -> bool
val ucompare : t -> t -> int

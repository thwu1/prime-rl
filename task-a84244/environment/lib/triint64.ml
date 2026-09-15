(* Three-limb 64-bit integer arithmetic.
 *
 * Representation: lo (24 bits), mi (24 bits), hi (16 bits)
 * Total: 24 + 24 + 16 = 64 bits
 * Value = hi * 2^48 + mi * 2^24 + lo  (as signed 64-bit)
 *
 * Inspired by js_of_ocaml's MlInt64 runtime representation.
 *)


[@@@warning "-32"]

type t = {
  lo : int;  (* 0..0xFFFFFF *)
  mi : int;  (* 0..0xFFFFFF *)
  hi : int;  (* 0..0xFFFF *)
}

let mask24 = 0xFFFFFF
let mask16 = 0xFFFF

let make ~lo ~mi ~hi =
  { lo = lo land mask24; mi = mi land mask24; hi = hi land mask16 }

let zero = { lo = 0; mi = 0; hi = 0 }
let one = { lo = 1; mi = 0; hi = 0 }
let minus_one = { lo = mask24; mi = mask24; hi = mask16 }
let min_int = { lo = 0; mi = 0; hi = 0x8000 }
let max_int = { lo = mask24; mi = mask24; hi = 0x7FFF }

let of_native (x : Int64.t) : t =
  let lo = Int64.to_int (Int64.logand x 0xFFFFFFL) in
  let mi = Int64.to_int (Int64.logand (Int64.shift_right_logical x 24) 0xFFFFFFL) in
  let hi = Int64.to_int (Int64.logand (Int64.shift_right_logical x 48) 0xFFFFL) in
  { lo; mi; hi }

let to_native (v : t) : Int64.t =
  let lo = Int64.of_int v.lo in
  let mi = Int64.shift_left (Int64.of_int v.mi) 24 in
  let hi = Int64.shift_left (Int64.of_int v.hi) 48 in
  Int64.logor lo (Int64.logor mi hi)

(* Arithmetic *)

let neg v =
  let lo = (- v.lo) in
  let mi = (- v.mi) + (lo asr 24) in
  let hi = (- v.hi) + (mi asr 24) in
  make ~lo ~mi ~hi

let add a b =
  let lo = a.lo + b.lo in
  let mi = a.mi + b.mi + (lo asr 24) in
  let hi = a.hi + b.hi + (mi asr 24) in
  make ~lo ~mi ~hi

let sub a b =
  let lo = a.lo - b.lo in
  let mi = a.mi - b.mi + (lo asr 24) in
  let hi = a.hi - b.hi + (mi asr 24) in
  make ~lo ~mi ~hi

let mul a b =
  let lo = a.lo * b.lo in
  let carry_lo = lo asr 24 in
  let mi = carry_lo + a.mi * b.lo + a.lo * b.mi in
  let carry_mi = mi asr 24 in
  let hi = carry_mi + a.hi * b.lo + a.mi * b.mi + a.lo * b.hi in
  make ~lo ~mi ~hi

let is_zero v = v.lo = 0 && v.mi = 0 && v.hi = 0

let is_neg v = v.hi land 0x8000 <> 0

(* Unsigned comparison *)
let ucompare a b =
  if a.hi > b.hi then 1
  else if a.hi < b.hi then -1
  else if a.mi > b.mi then 1
  else if a.mi < b.mi then -1
  else if a.lo > b.lo then 1
  else if a.lo < b.lo then -1
  else 0

let compare a b =
  if a.hi > b.hi then 1
  else if a.hi < b.hi then -1
  else if a.mi > b.mi then 1
  else if a.mi < b.mi then -1
  else if a.lo > b.lo then 1
  else if a.lo < b.lo then -1
  else 0

let equal a b = a.lo = b.lo && a.mi = b.mi && a.hi = b.hi

(* Bitwise *)
let logand a b = { lo = a.lo land b.lo; mi = a.mi land b.mi; hi = a.hi land b.hi }
let logor a b = { lo = a.lo lor b.lo; mi = a.mi lor b.mi; hi = a.hi lor b.hi }
let logxor a b = { lo = a.lo lxor b.lo; mi = a.mi lxor b.mi; hi = a.hi lxor b.hi }

(* Shifts *)

let shift_left v s =
  let s = s land 63 in
  if s = 0 then v
  else if s < 24 then
    make
      ~lo:(v.lo lsl s)
      ~mi:((v.mi lsl s) lor (v.lo lsr (24 - s)))
      ~hi:((v.hi lsl s) lor (v.mi lsr (24 - s)))
  else if s < 48 then
    make
      ~lo:0
      ~mi:(v.lo lsl (s - 24))
      ~hi:((v.mi lsl (s - 24)) lor (v.lo lsr (48 - s)))
  else
    make ~lo:0 ~mi:0 ~hi:(v.lo lsl (s - 48))

let shift_right_logical v s =
  let s = s land 63 in
  if s = 0 then v
  else if s < 24 then
    make
      ~lo:((v.lo lsr s) lor (v.mi lsl (24 - s)))
      ~mi:((v.mi lsr s) lor (v.hi lsl (24 - s)))
      ~hi:(v.hi lsr s)
  else if s < 48 then
    make
      ~lo:((v.mi lsr (s - 24)) lor (v.hi lsl (48 - s)))
      ~mi:(v.hi lsr (s - 24))
      ~hi:0
  else
    make ~lo:(v.hi lsr (s - 48)) ~mi:0 ~hi:0

let shift_right v s =
  let s = s land 63 in
  if s = 0 then v
  else if s < 24 then
    let h = ((v.hi lsl 16) asr 16) in
    make
      ~lo:((v.lo lsr s) lor (v.mi lsl (24 - s)))
      ~mi:((v.mi lsr s) lor (h lsl (24 - s)))
      ~hi:(((v.hi lsl 16) asr s) lsr 16)
  else if s < 48 then
    let sign = (v.hi lsl 16) asr 31 in
    let h = v.hi in
    make
      ~lo:((v.mi lsr (s - 24)) lor (h lsl (48 - s)))
      ~mi:(((v.hi lsl 16) asr (s - 24)) asr 16)
      ~hi:(sign land mask16)
  else
    let sign = (v.hi lsl 16) asr 31 in
    make
      ~lo:((v.hi lsl 16) asr (s - 32))
      ~mi:sign
      ~hi:(sign land mask16)

(* Division: long division on absolute values *)

type limbs = { mutable r_lo: int; mutable r_mi: int; mutable r_hi: int }

let lsl1 r =
  r.r_hi <- ((r.r_hi lsl 1) lor (r.r_mi lsr 23)) land mask16;
  r.r_mi <- ((r.r_mi lsl 1) lor (r.r_lo lsr 23)) land mask24;
  r.r_lo <- (r.r_lo lsl 1) land mask24

let lsr1 r =
  r.r_lo <- ((r.r_lo lsr 1) lor ((r.r_mi land 1) lsl 23)) land mask24;
  r.r_mi <- ((r.r_mi lsr 1) lor ((r.r_hi land 1) lsl 23)) land mask24;
  r.r_hi <- r.r_hi lsr 1

let to_limbs v = { r_lo = v.lo; r_mi = v.mi; r_hi = v.hi }
let of_limbs r = make ~lo:r.r_lo ~mi:r.r_mi ~hi:r.r_hi

let ucompare_limbs a b =
  if a.r_hi > b.r_hi then 1
  else if a.r_hi < b.r_hi then -1
  else if a.r_mi > b.r_mi then 1
  else if a.r_mi < b.r_mi then -1
  else if a.r_lo > b.r_lo then 1
  else if a.r_lo < b.r_lo then -1
  else 0

let sub_limbs a b =
  let lo = a.r_lo - b.r_lo in
  let mi = a.r_mi - b.r_mi + (lo asr 24) in
  let hi = a.r_hi - b.r_hi + (mi asr 24) in
  { r_lo = lo land mask24; r_mi = mi land mask24; r_hi = hi land mask16 }

let udivmod a b =
  let modulus = to_limbs a in
  let divisor = to_limbs b in
  let offset = ref 0 in
  while ucompare_limbs modulus divisor > 0 do
    incr offset;
    lsl1 divisor
  done;
  let quotient = { r_lo = 0; r_mi = 0; r_hi = 0 } in
  let modref = ref modulus in
  while !offset >= 0 do
    decr offset;
    lsl1 quotient;
    if ucompare_limbs !modref divisor >= 0 then begin
      quotient.r_lo <- quotient.r_lo + 1;
      modref := sub_limbs !modref divisor
    end;
    lsr1 divisor
  done;
  (of_limbs quotient, of_limbs !modref)

let div a b =
  if is_zero b then raise Division_by_zero;
  let sign = a.hi lxor b.hi in
  let a' = if is_neg a then neg a else a in
  let b' = if is_neg b then neg b else b in
  let (q, _) = udivmod a' b' in
  if sign land 0x8000 <> 0 then neg q else q

let modulo a b =
  if is_zero b then raise Division_by_zero;
  let sign = a.hi in
  let a' = if is_neg a then neg a else a in
  let b' = if is_neg b then neg b else b in
  let (_, r) = udivmod a' b' in
  if sign land 0x8000 <> 0 then neg r else r

(* String conversion *)

let to_string v =
  if is_zero v then "0"
  else
    let negative = is_neg v in
    let v = if negative then neg v else v in
    let buf = Buffer.create 20 in
    let ten = make ~lo:10 ~mi:0 ~hi:0 in
    let cur = ref v in
    while not (is_zero !cur) do
      let (q, r) = udivmod !cur ten in
      Buffer.add_char buf (Char.chr (r.lo + Char.code '0'));
      cur := q
    done;
    if negative then Buffer.add_char buf '-';
    let s = Buffer.contents buf in
    let n = String.length s in
    String.init n (fun i -> s.[n - 1 - i])

let of_string s =
  let len = String.length s in
  if len = 0 then failwith "Triint64.of_string";
  let sign = ref 1 in
  let i = ref 0 in
  if s.[0] = '-' then (sign := -1; i := 1)
  else if s.[0] = '+' then i := 1;
  if !i >= len then failwith "Triint64.of_string";
  let base = ref 10 in
  if !i + 1 < len && s.[!i] = '0' then begin
    match s.[!i + 1] with
    | 'x' | 'X' -> base := 16; i := !i + 2
    | 'o' | 'O' -> base := 8; i := !i + 2
    | 'b' | 'B' -> base := 2; i := !i + 2
    | _ -> ()
  end;
  if !i >= len then failwith "Triint64.of_string";
  let base_v = make ~lo:!base ~mi:0 ~hi:0 in
  let result = ref zero in
  let got_digit = ref false in
  while !i < len do
    let c = s.[!i] in
    if c = '_' then
      i := !i + 1
    else begin
      let d =
        if c >= '0' && c <= '9' then Char.code c - Char.code '0'
        else if c >= 'a' && c <= 'f' then Char.code c - Char.code 'a' + 10
        else if c >= 'A' && c <= 'F' then Char.code c - Char.code 'A' + 10
        else -1
      in
      if d < 0 || d >= !base then failwith "Triint64.of_string";
      got_digit := true;
      let d_v = make ~lo:d ~mi:0 ~hi:0 in
      result := add (mul !result base_v) d_v;
      i := !i + 1
    end
  done;
  if not !got_digit then failwith "Triint64.of_string";
  if !sign < 0 then neg !result else !result

let to_hex v =
  Printf.sprintf "%Lx" (to_native v)

(* MurmurHash3 mixing for Int64 custom blocks *)

let caml_mul_hash a b =
  let a = a land 0xFFFFFFFF in
  let b = b land 0xFFFFFFFF in
  let lo = (a land 0xFFFF) * b in
  let hi = (a lsr 16) * b in
  (lo + (hi lsl 16)) land 0xFFFFFFFF

let mix_int h d =
  let d = caml_mul_hash d (0xcc9e2d51 lor 0) in
  let d = ((d lsl 15) lor ((d land 0xFFFFFFFF) lsr 17)) land 0xFFFFFFFF in
  let d = caml_mul_hash d 0x1b873593 in
  let h = h lxor d in
  let h = ((h lsl 13) lor ((h land 0xFFFFFFFF) lsr 19)) land 0xFFFFFFFF in
  ((h + (h lsl 2)) + 0xe6546b64) land 0xFFFFFFFF

let mix_final h =
  let h = h lxor ((h land 0xFFFFFFFF) lsr 16) in
  let h = caml_mul_hash h (0x85ebca6b lor 0) in
  let h = h lxor ((h land 0xFFFFFFFF) lsr 13) in
  let h = caml_mul_hash h (0xc2b2ae35 lor 0) in
  let h = h lxor ((h land 0xFFFFFFFF) lsr 16) in
  h

let hash v =
  let lo32 = v.lo lor ((v.mi land 0xFF) lsl 24) in
  let hi32 = (v.mi lsr 8) lor (v.hi lsl 16) in
  let h = mix_int 0 lo32 in
  let h = mix_int h hi32 in
  let h = mix_final h in
  h land 0x3FFFFFFF

(* Marshal: produce bytes compatible with OCaml's Marshal for Int64 *)

let marshal v =
  Marshal.to_bytes (to_native v) []

let unmarshal buf =
  let n : Int64.t = Marshal.from_bytes buf 0 in
  of_native n

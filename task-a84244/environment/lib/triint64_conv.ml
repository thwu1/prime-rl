(* Extended conversions for three-limb 64-bit integers. *)


let to_float v =
  let n = Triint64.to_native v in
  Int64.to_float n

let of_float x =
  if Float.is_nan x || Float.is_infinite x then Triint64.zero
  else
    let n = Int64.of_float x in
    Triint64.of_native n

let to_int32 v =
  let n = Triint64.to_native v in
  Int64.to_int32 n

let of_int32 i =
  let n = Int64.of_int32 i in
  Triint64.of_native n

let unsigned_to_string v =
  if Triint64.is_zero v then "0"
  else if not (Triint64.is_neg v) then
    Triint64.to_string v
  else begin
    (* For negative values interpreted as unsigned, we need the
       unsigned decimal representation. We split the 64-bit value
       into high and low 32-bit halves and combine. *)
    let n = Triint64.to_native v in
    let lo = Int64.logand n 0xFFFFFFFFL in
    let hi = Int64.shift_right_logical n 32 in
    (* unsigned value = hi * 2^32 + lo *)
    let hi_f = Int64.to_float hi in
    let lo_f = Int64.to_float lo in
    let full = hi_f *. 4294967296.0 +. lo_f in
    Printf.sprintf "%.0f" full
  end

let popcount_byte b =
  let b = b - ((b lsr 1) land 0x55) in
  let b = (b land 0x33) + ((b lsr 2) land 0x33) in
  (b + (b lsr 4)) land 0x0F

let popcount v =
  let n = Triint64.to_native v in
  let count = ref 0 in
  for i = 0 to 7 do
    let byte = Int64.to_int (Int64.logand (Int64.shift_right_logical n (i * 8)) 0xFFL) in
    count := !count + popcount_byte byte
  done;
  !count

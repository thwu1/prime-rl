(* Test driver: differential testing of Triint64 against native Int64 *)


let () = Random.self_init ()

let random_int64 () =
  let b () = Int64.of_int (Random.bits ()) in
  let v = Int64.logor
    (Int64.shift_left (b ()) 48)
    (Int64.logor (Int64.shift_left (b ()) 24) (b ())) in
  if Random.bool () then Int64.neg v else v

let failures = ref 0
let tests_run = ref 0

let check name expected got =
  incr tests_run;
  if expected <> got then begin
    Printf.eprintf "FAIL %s: expected %s, got %s\n" name expected got;
    incr failures
  end

let check_int64 name (expected : Int64.t) (got : Int64.t) =
  check name (Int64.to_string expected) (Int64.to_string got)

let test_roundtrip () =
  let values = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
                0x00FFFFFFL; 0x01000000L; 0xFFFFFFFFFFFFFFFFL;
                0x7FFFFFFFL; 0x80000000L; 0x100000000L;
                0xFFFFFFFFFFFF0000L; 42L; (-42L)] in
  List.iter (fun v ->
    let t = Triint64.of_native v in
    let v' = Triint64.to_native t in
    check_int64 (Printf.sprintf "roundtrip(%Ld)" v) v v'
  ) values;
  for _ = 1 to 10000 do
    let v = random_int64 () in
    let t = Triint64.of_native v in
    let v' = Triint64.to_native t in
    check_int64 (Printf.sprintf "roundtrip_rand(%Ld)" v) v v'
  done

let test_add () =
  for _ = 1 to 5000 do
    let a = random_int64 () in
    let b = random_int64 () in
    let expected = Int64.add a b in
    let got = Triint64.to_native (Triint64.add (Triint64.of_native a) (Triint64.of_native b)) in
    check_int64 (Printf.sprintf "add(%Ld,%Ld)" a b) expected got
  done

let test_sub () =
  for _ = 1 to 5000 do
    let a = random_int64 () in
    let b = random_int64 () in
    let expected = Int64.sub a b in
    let got = Triint64.to_native (Triint64.sub (Triint64.of_native a) (Triint64.of_native b)) in
    check_int64 (Printf.sprintf "sub(%Ld,%Ld)" a b) expected got
  done

let test_mul () =
  let cases = [(0L, 0L); (1L, 1L); ((-1L), 1L); ((-1L), (-1L));
               (Int64.min_int, 1L); (Int64.min_int, (-1L));
               (Int64.max_int, 2L); (0x100L, 0x100L);
               (0xFFFFFFL, 0xFFFFFFL);
               (0x7FFFFFFFL, 0x7FFFFFFFL);
               (123456789L, 987654321L);
               ((-123456789L), 987654321L)] in
  List.iter (fun (a, b) ->
    let expected = Int64.mul a b in
    let got = Triint64.to_native (Triint64.mul (Triint64.of_native a) (Triint64.of_native b)) in
    check_int64 (Printf.sprintf "mul(%Ld,%Ld)" a b) expected got
  ) cases;
  for _ = 1 to 5000 do
    let a = random_int64 () in
    let b = random_int64 () in
    let expected = Int64.mul a b in
    let got = Triint64.to_native (Triint64.mul (Triint64.of_native a) (Triint64.of_native b)) in
    check_int64 (Printf.sprintf "mul_rand(%Ld,%Ld)" a b) expected got
  done

let test_neg () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int; 42L; (-42L)] in
  List.iter (fun a ->
    let expected = Int64.neg a in
    let got = Triint64.to_native (Triint64.neg (Triint64.of_native a)) in
    check_int64 (Printf.sprintf "neg(%Ld)" a) expected got
  ) cases;
  for _ = 1 to 2000 do
    let a = random_int64 () in
    let expected = Int64.neg a in
    let got = Triint64.to_native (Triint64.neg (Triint64.of_native a)) in
    check_int64 (Printf.sprintf "neg_rand(%Ld)" a) expected got
  done

let test_div () =
  let cases = [(10L, 3L); ((-10L), 3L); (10L, (-3L)); ((-10L), (-3L));
               (Int64.min_int, 1L); (Int64.min_int, (-1L));
               (Int64.min_int, 2L); (Int64.max_int, 1L);
               (Int64.max_int, (-1L)); (1L, 1L); (0L, 1L);
               (Int64.max_int, Int64.max_int);
               (Int64.min_int, Int64.min_int)] in
  List.iter (fun (a, b) ->
    let expected = Int64.div a b in
    let got = Triint64.to_native (Triint64.div (Triint64.of_native a) (Triint64.of_native b)) in
    check_int64 (Printf.sprintf "div(%Ld,%Ld)" a b) expected got
  ) cases;
  for _ = 1 to 3000 do
    let a = random_int64 () in
    let b = ref (random_int64 ()) in
    while !b = 0L do b := random_int64 () done;
    let expected = Int64.div a !b in
    let got = Triint64.to_native (Triint64.div (Triint64.of_native a) (Triint64.of_native !b)) in
    check_int64 (Printf.sprintf "div_rand(%Ld,%Ld)" a !b) expected got
  done

let test_modulo () =
  let cases = [(10L, 3L); ((-10L), 3L); (10L, (-3L)); ((-10L), (-3L));
               (Int64.min_int, 1L); (Int64.min_int, (-1L));
               (Int64.min_int, 2L); (Int64.max_int, (-1L));
               (0L, 1L)] in
  List.iter (fun (a, b) ->
    let expected = Int64.rem a b in
    let got = Triint64.to_native (Triint64.modulo (Triint64.of_native a) (Triint64.of_native b)) in
    check_int64 (Printf.sprintf "mod(%Ld,%Ld)" a b) expected got
  ) cases;
  for _ = 1 to 3000 do
    let a = random_int64 () in
    let b = ref (random_int64 ()) in
    while !b = 0L do b := random_int64 () done;
    let expected = Int64.rem a !b in
    let got = Triint64.to_native (Triint64.modulo (Triint64.of_native a) (Triint64.of_native !b)) in
    check_int64 (Printf.sprintf "mod_rand(%Ld,%Ld)" a !b) expected got
  done

let test_div_zero () =
  incr tests_run;
  (try
    let _ = Triint64.div Triint64.one Triint64.zero in
    Printf.eprintf "FAIL div_by_zero: no exception\n";
    incr failures
  with Division_by_zero -> ());
  incr tests_run;
  (try
    let _ = Triint64.modulo Triint64.one Triint64.zero in
    Printf.eprintf "FAIL mod_by_zero: no exception\n";
    incr failures
  with Division_by_zero -> ())

let test_shifts () =
  let values = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
                0xDEADBEEFCAFEL; (-42L); 0x7FFFFFFFL;
                0xFFFFFFFF00000000L; 0x123456789ABCDEF0L] in
  List.iter (fun v ->
    for s = 0 to 63 do
      let expected_shl = Int64.shift_left v s in
      let got_shl = Triint64.to_native (Triint64.shift_left (Triint64.of_native v) s) in
      check_int64 (Printf.sprintf "shl(%Ld,%d)" v s) expected_shl got_shl;

      let expected_shr = Int64.shift_right v s in
      let got_shr = Triint64.to_native (Triint64.shift_right (Triint64.of_native v) s) in
      check_int64 (Printf.sprintf "shr(%Ld,%d)" v s) expected_shr got_shr;

      let expected_lsr = Int64.shift_right_logical v s in
      let got_lsr = Triint64.to_native (Triint64.shift_right_logical (Triint64.of_native v) s) in
      check_int64 (Printf.sprintf "lsr(%Ld,%d)" v s) expected_lsr got_lsr;
    done
  ) values;
  for _ = 1 to 2000 do
    let v = random_int64 () in
    let s = Random.int 64 in
    let expected = Int64.shift_right v s in
    let got = Triint64.to_native (Triint64.shift_right (Triint64.of_native v) s) in
    check_int64 (Printf.sprintf "shr_rand(%Ld,%d)" v s) expected got
  done

let test_compare () =
  let cases = [(0L, 0L); (1L, 0L); (0L, 1L); ((-1L), 0L); (0L, (-1L));
               ((-1L), 1L); (1L, (-1L));
               (Int64.min_int, Int64.max_int);
               (Int64.max_int, Int64.min_int);
               (Int64.min_int, Int64.min_int);
               (Int64.max_int, Int64.max_int);
               (Int64.min_int, 0L); (0L, Int64.min_int);
               ((-1L), (-2L)); ((-2L), (-1L))] in
  List.iter (fun (a, b) ->
    let expected = Int64.compare a b in
    let got = Triint64.compare (Triint64.of_native a) (Triint64.of_native b) in
    let norm x = if x < 0 then -1 else if x > 0 then 1 else 0 in
    check (Printf.sprintf "compare(%Ld,%Ld)" a b)
      (string_of_int (norm expected)) (string_of_int (norm got))
  ) cases;
  for _ = 1 to 3000 do
    let a = random_int64 () in
    let b = random_int64 () in
    let expected = Int64.compare a b in
    let got = Triint64.compare (Triint64.of_native a) (Triint64.of_native b) in
    let norm x = if x < 0 then -1 else if x > 0 then 1 else 0 in
    check (Printf.sprintf "compare_rand(%Ld,%Ld)" a b)
      (string_of_int (norm expected)) (string_of_int (norm got))
  done

let test_bitwise () =
  for _ = 1 to 3000 do
    let a = random_int64 () in
    let b = random_int64 () in
    check_int64 (Printf.sprintf "and(%Ld,%Ld)" a b)
      (Int64.logand a b)
      (Triint64.to_native (Triint64.logand (Triint64.of_native a) (Triint64.of_native b)));
    check_int64 (Printf.sprintf "or(%Ld,%Ld)" a b)
      (Int64.logor a b)
      (Triint64.to_native (Triint64.logor (Triint64.of_native a) (Triint64.of_native b)));
    check_int64 (Printf.sprintf "xor(%Ld,%Ld)" a b)
      (Int64.logxor a b)
      (Triint64.to_native (Triint64.logxor (Triint64.of_native a) (Triint64.of_native b)))
  done

let test_to_string () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               42L; (-42L); 1000000000L; (-1000000000L);
               0x7FFFFFFFFFFFFFFFL; 0xFFFFFFFFFFFFFFFFL] in
  List.iter (fun v ->
    let expected = Int64.to_string v in
    let got = Triint64.to_string (Triint64.of_native v) in
    check (Printf.sprintf "to_string(%Ld)" v) expected got
  ) cases

let test_of_string () =
  let cases = ["0"; "1"; "-1"; "42"; "-42";
               "9223372036854775807";
               "-9223372036854775808";
               "0xFF"; "0xff"; "0XFF";
               "0o77"; "0O77";
               "0b1010"; "0B1010";
               "1_000_000"; "0x1_0"] in
  List.iter (fun s ->
    let expected = Int64.of_string s in
    let got = Triint64.to_native (Triint64.of_string s) in
    check_int64 (Printf.sprintf "of_string(%s)" s) expected got
  ) cases

let test_to_hex () =
  let cases = [0L; 1L; (-1L); 255L; 256L;
               Int64.max_int; Int64.min_int;
               0xDEADBEEFL; 42L] in
  List.iter (fun v ->
    let expected = Printf.sprintf "%Lx" v in
    let got = Triint64.to_hex (Triint64.of_native v) in
    check (Printf.sprintf "to_hex(%Ld)" v) expected got
  ) cases

let test_hash () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               42L; (-42L); 0xDEADBEEFCAFEL;
               0x123456789ABCDEF0L; 0xFFFFFFFFFFFFFFFFL] in
  List.iter (fun v ->
    let expected = Hashtbl.hash v in
    let got = Triint64.hash (Triint64.of_native v) in
    check (Printf.sprintf "hash(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  ) cases;
  for _ = 1 to 5000 do
    let v = random_int64 () in
    let expected = Hashtbl.hash v in
    let got = Triint64.hash (Triint64.of_native v) in
    check (Printf.sprintf "hash_rand(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  done

let test_marshal () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               42L; (-42L); 0xDEADBEEFCAFEL;
               0x123456789ABCDEF0L] in
  List.iter (fun v ->
    let expected_bytes = Marshal.to_bytes v [] in
    let got_bytes = Triint64.marshal (Triint64.of_native v) in
    check (Printf.sprintf "marshal_len(%Ld)" v)
      (string_of_int (Bytes.length expected_bytes))
      (string_of_int (Bytes.length got_bytes));
    check (Printf.sprintf "marshal_content(%Ld)" v)
      (Bytes.to_string expected_bytes)
      (Bytes.to_string got_bytes);
    let got = Triint64.to_native (Triint64.unmarshal expected_bytes) in
    check_int64 (Printf.sprintf "unmarshal(%Ld)" v) v got;
    let got2 = Triint64.to_native (Triint64.unmarshal got_bytes) in
    check_int64 (Printf.sprintf "marshal_roundtrip(%Ld)" v) v got2
  ) cases

(* Reference popcount using native Int64 *)
let native_popcount x =
  let x = ref x in
  let n = ref 0 in
  for _ = 0 to 63 do
    if Int64.logand !x 1L <> 0L then incr n;
    x := Int64.shift_right_logical !x 1
  done;
  !n

let test_popcount () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               42L; (-42L); 0xDEADBEEFCAFEL;
               0x123456789ABCDEF0L; 0xFFFFFFFFFFFFFFFFL;
               0xFFFF000000000000L; 0x0000FFFF00000000L;
               0x00000000FFFF0000L; 0x000000000000FFFFL;
               0x8000000000000000L; 0x0001000000000000L] in
  List.iter (fun v ->
    let expected = native_popcount v in
    let got = Triint64.popcount (Triint64.of_native v) in
    check (Printf.sprintf "popcount(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  ) cases;
  for _ = 1 to 5000 do
    let v = random_int64 () in
    let expected = native_popcount v in
    let got = Triint64.popcount (Triint64.of_native v) in
    check (Printf.sprintf "popcount_rand(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  done

(* Reference clz using native Int64 *)
let native_clz x =
  if x = 0L then 64
  else
    let n = ref 0 in
    let bit = ref (Int64.shift_left 1L 63) in
    while Int64.logand x !bit = 0L do
      incr n;
      bit := Int64.shift_right_logical !bit 1
    done;
    !n

let test_clz () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               42L; (-42L); 0xDEADBEEFCAFEL;
               0x123456789ABCDEF0L; 0xFFFFFFFFFFFFFFFFL;
               0x0001000000000000L; 0x0000010000000000L;
               0x0000000001000000L; 0x0000000000010000L;
               0x0000000000000100L; 0x0000000000000001L;
               0x8000000000000000L; 0x7FFFFFFFFFFFFFFFL;
               0x0000800000000000L; 0x0000000000800000L] in
  List.iter (fun v ->
    let expected = native_clz v in
    let got = Triint64.clz (Triint64.of_native v) in
    check (Printf.sprintf "clz(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  ) cases;
  for _ = 1 to 5000 do
    let v = random_int64 () in
    let expected = native_clz v in
    let got = Triint64.clz (Triint64.of_native v) in
    check (Printf.sprintf "clz_rand(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  done

(* Reference rotate_left using native Int64 *)
let native_rotate_left x s =
  let s = s land 63 in
  if s = 0 then x
  else
    Int64.logor
      (Int64.shift_left x s)
      (Int64.shift_right_logical x (64 - s))

let test_rotate_left () =
  let values = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
                0xDEADBEEFCAFEL; (-42L); 0x7FFFFFFFL;
                0xFFFFFFFF00000000L; 0x123456789ABCDEF0L;
                0x8000000000000001L; 0x0000000000000001L] in
  List.iter (fun v ->
    for s = 0 to 63 do
      let expected = native_rotate_left v s in
      let got = Triint64.to_native (Triint64.rotate_left (Triint64.of_native v) s) in
      check_int64 (Printf.sprintf "rotl(%Ld,%d)" v s) expected got
    done
  ) values;
  for _ = 1 to 3000 do
    let v = random_int64 () in
    let s = Random.int 64 in
    let expected = native_rotate_left v s in
    let got = Triint64.to_native (Triint64.rotate_left (Triint64.of_native v) s) in
    check_int64 (Printf.sprintf "rotl_rand(%Ld,%d)" v s) expected got
  done

let () =
  test_roundtrip ();
  test_add ();
  test_sub ();
  test_mul ();
  test_neg ();
  test_div ();
  test_modulo ();
  test_div_zero ();
  test_shifts ();
  test_compare ();
  test_bitwise ();
  test_to_string ();
  test_of_string ();
  test_to_hex ();
  test_hash ();
  test_marshal ();
  test_popcount ();
  test_clz ();
  test_rotate_left ();
  if !failures = 0 then
    Printf.printf "ALL TESTS PASSED (%d tests)\n" !tests_run
  else begin
    Printf.eprintf "FAILED: %d/%d tests failed\n" !failures !tests_run;
    exit 1
  end

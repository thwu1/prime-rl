(* Differential test driver: Triint64 + Triint64_conv against native Int64 *)


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

(* Triint64_conv tests *)

let test_to_float () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               42L; (-42L); 0x1FFFFFFFFFFFFFL;
               0x20000000000000L; 0x20000000000001L;
               Int64.of_string "4611686018427387903";
               Int64.of_string "-4611686018427387903"] in
  List.iter (fun v ->
    let expected = Int64.to_float v in
    let got = Triint64_conv.to_float (Triint64.of_native v) in
    check (Printf.sprintf "to_float(%Ld)" v)
      (Printf.sprintf "%.17g" expected) (Printf.sprintf "%.17g" got)
  ) cases;
  for _ = 1 to 3000 do
    let v = random_int64 () in
    let expected = Int64.to_float v in
    let got = Triint64_conv.to_float (Triint64.of_native v) in
    check (Printf.sprintf "to_float_rand(%Ld)" v)
      (Printf.sprintf "%.17g" expected) (Printf.sprintf "%.17g" got)
  done

let test_of_float () =
  let cases = [0.0; 1.0; (-1.0); 42.0; (-42.0); 1e18; (-1e18);
               9.22337203685478e+18;
               Float.infinity; Float.neg_infinity; Float.nan;
               0.5; (-0.5); 0.999; (-0.999);
               4503599627370496.0; (-4503599627370496.0)] in
  List.iter (fun f ->
    let expected =
      if Float.is_nan f || Float.is_infinite f then 0L
      else Int64.of_float f
    in
    let got = Triint64.to_native (Triint64_conv.of_float f) in
    check_int64 (Printf.sprintf "of_float(%g)" f) expected got
  ) cases;
  for _ = 1 to 3000 do
    let v = random_int64 () in
    let f = Int64.to_float v in
    let expected = Int64.of_float f in
    let got = Triint64.to_native (Triint64_conv.of_float f) in
    check_int64 (Printf.sprintf "of_float_rand(%g)" f) expected got
  done

let test_to_int32 () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               0x7FFFFFFFL; (-0x80000000L); 0x100000000L;
               42L; (-42L); 0xFFFFFFFL; 0xFFFFFFFFL] in
  List.iter (fun v ->
    let expected = Int64.to_int32 v in
    let got = Triint64_conv.to_int32 (Triint64.of_native v) in
    check (Printf.sprintf "to_int32(%Ld)" v)
      (Int32.to_string expected) (Int32.to_string got)
  ) cases

let test_of_int32 () =
  let cases = [0l; 1l; (-1l); Int32.min_int; Int32.max_int; 42l; (-42l)] in
  List.iter (fun i ->
    let expected = Int64.of_int32 i in
    let got = Triint64.to_native (Triint64_conv.of_int32 i) in
    check_int64 (Printf.sprintf "of_int32(%ld)" i) expected got
  ) cases

let test_unsigned_to_string () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               42L; 0xFFFFFFFFFFFFFFFFL; 0xFFFFFFFFL;
               0x100000000L; (-2L)] in
  List.iter (fun v ->
    let expected = Printf.sprintf "%Lu" v in
    let got = Triint64_conv.unsigned_to_string (Triint64.of_native v) in
    check (Printf.sprintf "unsigned_to_string(%Ld)" v) expected got
  ) cases

let popcount_ref n =
  let count = ref 0 in
  for i = 0 to 63 do
    if Int64.logand (Int64.shift_right_logical n i) 1L = 1L then
      incr count
  done;
  !count

let test_popcount () =
  let cases = [0L; 1L; (-1L); Int64.min_int; Int64.max_int;
               0xFFL; 0xAAAAAAAAAAAAAAAAL; 0x5555555555555555L;
               42L; 0xDEADBEEFCAFEL] in
  List.iter (fun v ->
    let expected = popcount_ref v in
    let got = Triint64_conv.popcount (Triint64.of_native v) in
    check (Printf.sprintf "popcount(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  ) cases;
  for _ = 1 to 3000 do
    let v = random_int64 () in
    let expected = popcount_ref v in
    let got = Triint64_conv.popcount (Triint64.of_native v) in
    check (Printf.sprintf "popcount_rand(%Ld)" v)
      (string_of_int expected) (string_of_int got)
  done

(* Property-based tests *)

let test_algebraic_properties () =
  for _ = 1 to 2000 do
    let a_n = random_int64 () in
    let b_n = random_int64 () in
    let c_n = random_int64 () in
    let a = Triint64.of_native a_n in
    let b = Triint64.of_native b_n in
    let c = Triint64.of_native c_n in
    (* add commutativity *)
    check_int64 (Printf.sprintf "add_comm(%Ld,%Ld)" a_n b_n)
      (Triint64.to_native (Triint64.add a b))
      (Triint64.to_native (Triint64.add b a));
    (* add associativity *)
    check_int64 (Printf.sprintf "add_assoc(%Ld,%Ld,%Ld)" a_n b_n c_n)
      (Triint64.to_native (Triint64.add (Triint64.add a b) c))
      (Triint64.to_native (Triint64.add a (Triint64.add b c)));
    (* mul commutativity *)
    check_int64 (Printf.sprintf "mul_comm(%Ld,%Ld)" a_n b_n)
      (Triint64.to_native (Triint64.mul a b))
      (Triint64.to_native (Triint64.mul b a));
    (* add identity *)
    check_int64 (Printf.sprintf "add_id(%Ld)" a_n)
      (Triint64.to_native a)
      (Triint64.to_native (Triint64.add a Triint64.zero));
    (* mul identity *)
    check_int64 (Printf.sprintf "mul_id(%Ld)" a_n)
      (Triint64.to_native a)
      (Triint64.to_native (Triint64.mul a Triint64.one));
    (* neg involution *)
    check_int64 (Printf.sprintf "neg_neg(%Ld)" a_n)
      (Triint64.to_native a)
      (Triint64.to_native (Triint64.neg (Triint64.neg a)));
    (* a + neg a = 0 *)
    check_int64 (Printf.sprintf "add_neg(%Ld)" a_n)
      0L
      (Triint64.to_native (Triint64.add a (Triint64.neg a)));
    (* compare consistency with native *)
    let cmp = Triint64.compare a b in
    let expected_cmp = Int64.compare a_n b_n in
    let norm x = if x < 0 then -1 else if x > 0 then 1 else 0 in
    check (Printf.sprintf "compare_prop(%Ld,%Ld)" a_n b_n)
      (string_of_int (norm expected_cmp)) (string_of_int (norm cmp));
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
  test_to_float ();
  test_of_float ();
  test_to_int32 ();
  test_of_int32 ();
  test_unsigned_to_string ();
  test_popcount ();
  test_algebraic_properties ();
  if !failures = 0 then
    Printf.printf "ALL TESTS PASSED (%d tests)\n" !tests_run
  else begin
    Printf.eprintf "FAILED: %d/%d tests failed\n" !failures !tests_run;
    exit 1
  end

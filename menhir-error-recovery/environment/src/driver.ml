(* Basic parser driver — stub implementation.
   Uses the monolithic parser API. Stops at the first error.
   Does not output the AST and does not perform error recovery. *)

let read_all ic =
  let buf = Buffer.create 4096 in
  (try while true do Buffer.add_char buf (input_char ic) done
   with End_of_file -> ());
  Buffer.contents buf

let () =
  let input = read_all stdin in
  let lexbuf = Lexing.from_string input in
  lexbuf.lex_curr_p <- {
    lexbuf.lex_curr_p with Lexing.pos_fname = "<stdin>"; pos_lnum = 1
  };
  try
    let _ast = Parser.program Lexer.token lexbuf in
    print_string "{\"status\":\"ok\"}\n"
  with
  | Parser.Error ->
    let pos = lexbuf.Lexing.lex_curr_p in
    Printf.printf
      "{\"status\":\"error\",\"errors\":[{\"line\":%d,\"col\":%d,\"message\":\"syntax error\"}]}\n"
      pos.Lexing.pos_lnum
      (pos.Lexing.pos_cnum - pos.Lexing.pos_bol + 1)
  | Lexer.Error msg ->
    Printf.printf
      "{\"status\":\"error\",\"errors\":[{\"line\":1,\"col\":1,\"message\":\"%s\"}]}\n"
      msg

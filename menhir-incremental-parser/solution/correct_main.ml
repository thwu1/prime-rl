module I = Miniml.Parser.MenhirInterpreter

let rec loop lexbuf (checkpoint : Miniml.Ast.expr I.checkpoint) =
  match checkpoint with
  | I.InputNeeded _env ->
    let token = Miniml.Lexer.token lexbuf in
    let startp = lexbuf.Lexing.lex_start_p in
    let endp = lexbuf.Lexing.lex_curr_p in
    loop lexbuf (I.offer checkpoint (token, startp, endp))
  | I.Shifting _ | I.AboutToReduce _ ->
    loop lexbuf (I.resume checkpoint)
  | I.HandlingError _env ->
    let pos = lexbuf.Lexing.lex_start_p in
    let line = pos.Lexing.pos_lnum in
    let col = pos.Lexing.pos_cnum - pos.Lexing.pos_bol in
    Printf.eprintf "Syntax error at line %d, column %d.\n" line col;
    exit 1
  | I.Accepted result ->
    result
  | I.Rejected ->
    Printf.eprintf "Syntax error: input rejected.\n";
    exit 1

let () =
  let lexbuf = Lexing.from_channel stdin in
  lexbuf.Lexing.lex_curr_p <-
    { lexbuf.Lexing.lex_curr_p with Lexing.pos_fname = "<stdin>" };
  let checkpoint =
    Miniml.Parser.Incremental.program lexbuf.Lexing.lex_curr_p
  in
  try
    let ast = loop lexbuf checkpoint in
    print_endline (Miniml.Printer.print_expr ast)
  with
  | Miniml.Lexer.LexError msg ->
    Printf.eprintf "Lexical error: %s\n" msg;
    exit 1

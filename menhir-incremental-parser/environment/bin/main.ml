let () =
  let lexbuf = Lexing.from_channel stdin in
  try
    let ast = Miniml.Parser.program Miniml.Lexer.token lexbuf in
    print_endline (Miniml.Printer.print_expr ast)
  with
  | Miniml.Parser.Error ->
    Printf.eprintf "Parse error\n";
    exit 1
  | Miniml.Lexer.LexError msg ->
    Printf.eprintf "Lexical error: %s\n" msg;
    exit 1

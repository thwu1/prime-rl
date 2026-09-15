
(* Parser driver with incremental error recovery using Menhir's table-based
   incremental API (loop_handle_undo) and the acceptable-token query for
   context-sensitive error messages.

   Error recovery strategy: after each error, record it and restart a fresh
   parser from the current lexbuf position.  A monotonically-increasing
   position guard prevents infinite loops — if the lexbuf has not advanced
   past the last error site we stop. *)

module I = Parser.MenhirInterpreter

(* -------------------------------------------------------------------------- *)
(* Utilities                                                                  *)
(* -------------------------------------------------------------------------- *)

let read_all ic =
  let buf = Buffer.create 4096 in
  (try while true do Buffer.add_char buf (input_char ic) done
   with End_of_file -> ());
  Buffer.contents buf

(* -------------------------------------------------------------------------- *)
(* JSON helpers                                                               *)
(* -------------------------------------------------------------------------- *)

let json_str s =
  let buf = Buffer.create (String.length s + 2) in
  Buffer.add_char buf '"';
  String.iter (fun c ->
    match c with
    | '"'  -> Buffer.add_string buf "\\\""
    | '\\' -> Buffer.add_string buf "\\\\"
    | '\n' -> Buffer.add_string buf "\\n"
    | '\t' -> Buffer.add_string buf "\\t"
    | '\r' -> Buffer.add_string buf "\\r"
    | c when Char.code c < 32 ->
      Buffer.add_string buf (Printf.sprintf "\\u%04x" (Char.code c))
    | c -> Buffer.add_char buf c
  ) s;
  Buffer.add_char buf '"';
  Buffer.contents buf

(* -------------------------------------------------------------------------- *)
(* AST -> JSON                                                                *)
(* -------------------------------------------------------------------------- *)

let binop_s = function
  | Ast.Add -> "+" | Ast.Sub -> "-" | Ast.Mul -> "*" | Ast.Div -> "/"
  | Ast.Eq -> "==" | Ast.Ne -> "!="
  | Ast.Lt -> "<" | Ast.Le -> "<=" | Ast.Gt -> ">" | Ast.Ge -> ">="
  | Ast.And -> "&&" | Ast.Or -> "||"

let rec to_json = function
  | Ast.Int n ->
    Printf.sprintf "{\"tag\":\"int\",\"value\":%d}" n
  | Ast.Bool b ->
    Printf.sprintf "{\"tag\":\"bool\",\"value\":%b}" b
  | Ast.Var x ->
    Printf.sprintf "{\"tag\":\"var\",\"name\":%s}" (json_str x)
  | Ast.BinOp (op, l, r) ->
    Printf.sprintf "{\"tag\":\"binop\",\"op\":%s,\"left\":%s,\"right\":%s}"
      (json_str (binop_s op)) (to_json l) (to_json r)
  | Ast.UnaryMinus e ->
    Printf.sprintf "{\"tag\":\"neg\",\"expr\":%s}" (to_json e)
  | Ast.Let (x, e1, e2) ->
    Printf.sprintf "{\"tag\":\"let\",\"name\":%s,\"bind\":%s,\"body\":%s}"
      (json_str x) (to_json e1) (to_json e2)
  | Ast.If (c, t, e) ->
    Printf.sprintf "{\"tag\":\"if\",\"cond\":%s,\"then\":%s,\"else\":%s}"
      (to_json c) (to_json t) (to_json e)
  | Ast.Fun (x, e) ->
    Printf.sprintf "{\"tag\":\"fun\",\"param\":%s,\"body\":%s}"
      (json_str x) (to_json e)
  | Ast.App (f, a) ->
    Printf.sprintf "{\"tag\":\"app\",\"fn\":%s,\"arg\":%s}"
      (to_json f) (to_json a)
  | Ast.Seq (e1, e2) ->
    Printf.sprintf "{\"tag\":\"seq\",\"first\":%s,\"second\":%s}"
      (to_json e1) (to_json e2)

(* -------------------------------------------------------------------------- *)
(* Error tracking                                                             *)
(* -------------------------------------------------------------------------- *)

type err = { line : int; col : int; msg : string }

let errors : err list ref = ref []

(* -------------------------------------------------------------------------- *)
(* Context-sensitive "expected" description via I.acceptable                  *)
(* -------------------------------------------------------------------------- *)

let expected_desc (cp : Ast.expr I.checkpoint) pos =
  let ok tok = I.acceptable cp tok pos in
  (* Distinguish "identifier only" from "any expression starter" *)
  let ident_ok = ok (Parser.IDENT "x") in
  let expr_ok  = ok (Parser.INT 0) || ok Parser.TRUE || ok Parser.LPAREN in
  if ident_ok && not expr_ok then
    "identifier"
  else if ident_ok || expr_ok then
    "expression"
  else if ok Parser.THEN then
    "'then'"
  else if ok Parser.ELSE then
    "'else'"
  else if ok Parser.EQUAL then
    "'='"
  else if ok Parser.IN then
    "'in'"
  else if ok Parser.ARROW then
    "'->'"
  else if ok Parser.RPAREN then
    "closing ')'"
  else if ok Parser.SEMICOLON || ok Parser.EOF || ok Parser.PLUS then
    "operator or end of input"
  else
    "valid token"

(* -------------------------------------------------------------------------- *)
(* Main incremental parsing loop with error recovery                          *)
(* -------------------------------------------------------------------------- *)

let parse input =
  errors := [];
  let lexbuf = Lexing.from_string input in
  lexbuf.lex_curr_p <- {
    lexbuf.lex_curr_p with Lexing.pos_fname = "<stdin>"; pos_lnum = 1
  };
  let supplier = I.lexer_lexbuf_to_supplier Lexer.token lexbuf in

  (* [go last_pos] starts a fresh parse from the current lexbuf position.
     [last_pos] is the lexbuf pos_cnum after the previous error; if the
     current position has not advanced past it we stop (prevents loops). *)
  let rec go last_pos =
    let checkpoint = Parser.Incremental.program lexbuf.Lexing.lex_curr_p in
    I.loop_handle_undo
      (fun v -> Some v)                                  (* on success *)
      (fun (inp_cp : Ast.expr I.checkpoint)               (* last InputNeeded *)
           (err_cp : Ast.expr I.checkpoint) ->             (* HandlingError *)
        (* Position guard: the supplier already consumed the offending
           token, so lex_curr_p is past it.  If we haven't moved since
           the last error (e.g. stuck at EOF) we bail out. *)
        let current_pos = lexbuf.Lexing.lex_curr_p.Lexing.pos_cnum in
        if current_pos <= last_pos then
          None
        else begin
          (* Extract error position from the HandlingError environment *)
          let env =
            match err_cp with
            | I.HandlingError env -> env
            | _ ->
              (match inp_cp with
               | I.InputNeeded env -> env
               | _ -> assert false)
          in
          let startp, endp = I.positions env in
          let line = startp.Lexing.pos_lnum in
          let col  = startp.Lexing.pos_cnum - startp.Lexing.pos_bol + 1 in

          (* Extract offending token text from source *)
          let tok_text =
            let s = startp.Lexing.pos_cnum and e = endp.Lexing.pos_cnum in
            if s >= String.length input then "end of input"
            else
              let len = min (e - s) (String.length input - s) in
              if len <= 0 then "end of input"
              else String.sub input s len
          in

          (* Build context-sensitive message *)
          let exp = expected_desc inp_cp startp in
          let message =
            Printf.sprintf "unexpected '%s', expected %s" tok_text exp
          in
          errors := { line; col; msg = message } :: !errors;

          (* Restart a fresh parser from the current lexbuf position.
             The offending token has already been consumed by the supplier,
             so the next token read will be whatever follows it. *)
          go current_pos
        end)
      supplier
      checkpoint
  in

  let result =
    try go (-1)
    with Lexer.Error m ->
      let p = lexbuf.Lexing.lex_curr_p in
      errors := {
        line = p.Lexing.pos_lnum;
        col  = p.Lexing.pos_cnum - p.Lexing.pos_bol + 1;
        msg  = m
      } :: !errors;
      None
  in
  (result, List.rev !errors)

(* -------------------------------------------------------------------------- *)
(* Entry point                                                                *)
(* -------------------------------------------------------------------------- *)

let () =
  let input = read_all stdin in
  match parse input with
  | (Some ast, []) ->
    Printf.printf "{\"status\":\"ok\",\"ast\":%s}\n" (to_json ast)
  | (_, errs) when errs <> [] ->
    let es = List.map (fun e ->
      Printf.sprintf "{\"line\":%d,\"col\":%d,\"message\":%s}"
        e.line e.col (json_str e.msg)
    ) errs in
    Printf.printf "{\"status\":\"error\",\"errors\":[%s]}\n"
      (String.concat "," es)
  | _ ->
    Printf.printf "{\"status\":\"error\",\"errors\":[]}\n"

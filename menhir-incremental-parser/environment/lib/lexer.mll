{
open Parser

exception LexError of string
}

let digit = ['0'-'9']
let alpha = ['a'-'z' 'A'-'Z' '_']

rule token = parse
  | [' ' '\t' '\r']+ { token lexbuf }
  | '\n' { Lexing.new_line lexbuf; token lexbuf }
  | "(*" { comment 1 lexbuf }
  | digit+ as n { INT (int_of_string n) }
  | "true" { TRUE }
  | "false" { FALSE }
  | "let" { LET }
  | "rec" { REC }
  | "in" { IN }
  | "if" { IF }
  | "then" { THEN }
  | "else" { ELSE }
  | "fun" { FUN }
  | "match" { MATCH }
  | "with" { WITH }
  | "not" { NOT }
  | "_" { UNDERSCORE }
  | ['a'-'z'] (alpha | digit | '\'')* as s { IDENT s }
  | "+" { PLUS }
  | "->" { ARROW }
  | "-" { MINUS }
  | "*" { TIMES }
  | "/" { DIV }
  | "<>" { NEQ }
  | "<=" { LE }
  | ">=" { GE }
  | "<" { LT }
  | ">" { GT }
  | "=" { EQ }
  | "&&" { AMPAMP }
  | "||" { BARBAR }
  | "::" { COLONCOLON }
  | "(" { LPAREN }
  | ")" { RPAREN }
  | "[" { LBRACKET }
  | "]" { RBRACKET }
  | "," { COMMA }
  | ";" { SEMI }
  | "|" { BAR }
  | eof { EOF }
  | _ as c { raise (LexError (Printf.sprintf "Unexpected character: '%c'" c)) }

and comment depth = parse
  | "(*" { comment (depth + 1) lexbuf }
  | "*)" { if depth = 1 then token lexbuf else comment (depth - 1) lexbuf }
  | '\n' { Lexing.new_line lexbuf; comment depth lexbuf }
  | _ { comment depth lexbuf }
  | eof { raise (LexError "Unterminated comment") }

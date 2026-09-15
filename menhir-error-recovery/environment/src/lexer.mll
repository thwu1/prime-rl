{
open Parser
exception Error of string
}

let digit = ['0'-'9']
let alpha = ['a'-'z' 'A'-'Z' '_']
let alnum = alpha | digit

rule token = parse
  | [' ' '\t']+    { token lexbuf }
  | '\n'           { Lexing.new_line lexbuf; token lexbuf }
  | digit+ as n    { INT (int_of_string n) }
  | "true"         { TRUE }
  | "false"        { FALSE }
  | "let"          { LET }
  | "in"           { IN }
  | "if"           { IF }
  | "then"         { THEN }
  | "else"         { ELSE }
  | "fun"          { FUN }
  | "->"           { ARROW }
  | "=="           { EQ }
  | "!="           { NEQ }
  | "<="           { LE }
  | ">="           { GE }
  | '+'            { PLUS }
  | '-'            { MINUS }
  | '*'            { TIMES }
  | '/'            { DIV }
  | '<'            { LT }
  | '>'            { GT }
  | "&&"           { AND }
  | "||"           { OR }
  | '('            { LPAREN }
  | ')'            { RPAREN }
  | ';'            { SEMICOLON }
  | '='            { EQUAL }
  | alpha alnum* as s { IDENT s }
  | eof            { EOF }
  | _ as c         { raise (Error (Printf.sprintf "unexpected character: %c" c)) }

export enum TokenType {
  // Literals
  Number = 'Number',
  String = 'String',

  // Keywords
  True = 'True',
  False = 'False',
  Null = 'Null',
  In = 'In',

  // Identifier
  Identifier = 'Identifier',

  // Operators
  Plus = 'Plus',
  Minus = 'Minus',
  Star = 'Star',
  Slash = 'Slash',
  Percent = 'Percent',

  EqualEqual = 'EqualEqual',
  BangEqual = 'BangEqual',
  Less = 'Less',
  LessEqual = 'LessEqual',
  Greater = 'Greater',
  GreaterEqual = 'GreaterEqual',

  And = 'And',
  Or = 'Or',
  Bang = 'Bang',

  // Delimiters
  LeftParen = 'LeftParen',
  RightParen = 'RightParen',
  LeftBracket = 'LeftBracket',
  RightBracket = 'RightBracket',
  LeftBrace = 'LeftBrace',
  RightBrace = 'RightBrace',
  Comma = 'Comma',
  Dot = 'Dot',

  EOF = 'EOF',
}

export interface Token {
  type: TokenType;
  value: string;
  pos: number;
}

export type Expr =
  | { kind: 'literal'; value: number | string | boolean | null }
  | { kind: 'array'; elements: Expr[] }
  | { kind: 'object' }
  | { kind: 'identifier'; name: string }
  | { kind: 'unary'; op: string; operand: Expr }
  | { kind: 'binary'; op: string; left: Expr; right: Expr }
  | { kind: 'call'; name: string; args: Expr[] }
  | { kind: 'member'; object: Expr; property: string }
  | { kind: 'index'; object: Expr; index: Expr };

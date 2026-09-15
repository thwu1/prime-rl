
export enum TokenType {
  Number = 'Number',
  String = 'String',
  Boolean = 'Boolean',
  Null = 'Null',
  Identifier = 'Identifier',
  LeftParen = 'LeftParen',
  RightParen = 'RightParen',
  LeftBracket = 'LeftBracket',
  RightBracket = 'RightBracket',
  LeftBrace = 'LeftBrace',
  RightBrace = 'RightBrace',
  Comma = 'Comma',
  Dot = 'Dot',
  Plus = 'Plus',
  Minus = 'Minus',
  Star = 'Star',
  Slash = 'Slash',
  Percent = 'Percent',
  Bang = 'Bang',
  BangEqual = 'BangEqual',
  Equal = 'Equal',
  EqualEqual = 'EqualEqual',
  Less = 'Less',
  LessEqual = 'LessEqual',
  Greater = 'Greater',
  GreaterEqual = 'GreaterEqual',
  And = 'And',
  Or = 'Or',
  In = 'In',
  EOF = 'EOF',
}

export interface Token {
  type: TokenType;
  value: string;
  position: number;
}

export type ASTNode =
  | NumberLiteral
  | StringLiteral
  | BooleanLiteral
  | NullLiteral
  | ArrayLiteral
  | ObjectLiteral
  | Identifier
  | MemberAccess
  | IndexAccess
  | FunctionCall
  | UnaryOp
  | BinaryOp
  | InExpression;

export interface NumberLiteral { type: 'NumberLiteral'; value: number; }
export interface StringLiteral { type: 'StringLiteral'; value: string; }
export interface BooleanLiteral { type: 'BooleanLiteral'; value: boolean; }
export interface NullLiteral { type: 'NullLiteral'; }
export interface ArrayLiteral { type: 'ArrayLiteral'; elements: ASTNode[]; }
export interface ObjectLiteral { type: 'ObjectLiteral'; }
export interface Identifier { type: 'Identifier'; name: string; }
export interface MemberAccess { type: 'MemberAccess'; object: ASTNode; property: string; }
export interface IndexAccess { type: 'IndexAccess'; object: ASTNode; index: ASTNode; }
export interface FunctionCall { type: 'FunctionCall'; name: string; args: ASTNode[]; }
export interface UnaryOp { type: 'UnaryOp'; operator: string; operand: ASTNode; }
export interface BinaryOp { type: 'BinaryOp'; operator: string; left: ASTNode; right: ASTNode; }
export interface InExpression { type: 'InExpression'; value: ASTNode; collection: ASTNode; }

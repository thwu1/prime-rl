import { createToken, Lexer } from "chevrotain";

export const WhiteSpace = createToken({
  name: "WhiteSpace",
  pattern: /\s+/,
  group: Lexer.SKIPPED,
});

export const LineComment = createToken({
  name: "LineComment",
  pattern: /\/\/[^\n]*/,
  group: Lexer.SKIPPED,
});

export const LCurly = createToken({ name: "LCurly", pattern: /{/ });
export const RCurly = createToken({ name: "RCurly", pattern: /}/ });
export const LBracket = createToken({ name: "LBracket", pattern: /\[/ });
export const RBracket = createToken({ name: "RBracket", pattern: /\]/ });
export const Colon = createToken({ name: "Colon", pattern: /:/ });
export const SemiColon = createToken({ name: "SemiColon", pattern: /;/ });
export const Comma = createToken({ name: "Comma", pattern: /,/ });
export const QuestionMark = createToken({ name: "QuestionMark", pattern: /\?/ });

export const Identifier = createToken({
  name: "Identifier",
  pattern: /[a-zA-Z_]\w*/,
});

export const TypeKeyword = createToken({
  name: "TypeKeyword",
  pattern: /type/,
});

export const EnumKeyword = createToken({
  name: "EnumKeyword",
  pattern: /enum/,
});

export const allTokens = [
  WhiteSpace,
  LineComment,
  LCurly,
  RCurly,
  LBracket,
  RBracket,
  Colon,
  SemiColon,
  Comma,
  Identifier,
  TypeKeyword,
  EnumKeyword,
];

export const SchemaLexer = new Lexer(allTokens);

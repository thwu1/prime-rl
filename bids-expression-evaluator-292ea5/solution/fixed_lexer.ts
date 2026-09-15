import { Token, TokenType } from './types';

const KEYWORDS: Record<string, TokenType> = {
  'true': TokenType.True,
  'false': TokenType.False,
  'null': TokenType.Null,
  'in': TokenType.In,
};

export function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;

  while (i < input.length) {
    if (/\s/.test(input[i])) { i++; continue; }

    const start = i;
    const ch = input[i];

    // String literals (single or double quoted)
    if (ch === '"' || ch === "'") {
      i++;
      let str = '';
      while (i < input.length && input[i] !== ch) {
        if (input[i] === '\\') {
          i++;
          if (i < input.length) str += input[i];
        } else {
          str += input[i];
        }
        i++;
      }
      if (i < input.length) i++;
      tokens.push({ type: TokenType.String, value: str, pos: start });
      continue;
    }

    // Number literals
    if (/\d/.test(ch) || (ch === '.' && i + 1 < input.length && /\d/.test(input[i + 1]))) {
      let num = '';
      while (i < input.length && /[\d.]/.test(input[i])) {
        num += input[i];
        i++;
      }
      tokens.push({ type: TokenType.Number, value: num, pos: start });
      continue;
    }

    // Identifiers and keywords
    if (/[a-zA-Z_]/.test(ch)) {
      let ident = '';
      while (i < input.length && /[a-zA-Z0-9_]/.test(input[i])) {
        ident += input[i];
        i++;
      }
      const kw = KEYWORDS[ident];
      tokens.push({ type: kw || TokenType.Identifier, value: ident, pos: start });
      continue;
    }

    // Two-character operators
    if (ch === '&' && input[i + 1] === '&') {
      tokens.push({ type: TokenType.And, value: '&&', pos: start }); i += 2; continue;
    }
    if (ch === '|' && input[i + 1] === '|') {
      tokens.push({ type: TokenType.Or, value: '||', pos: start }); i += 2; continue;
    }
    if (ch === '=' && input[i + 1] === '=') {
      tokens.push({ type: TokenType.EqualEqual, value: '==', pos: start }); i += 2; continue;
    }
    if (ch === '!' && input[i + 1] === '=') {
      tokens.push({ type: TokenType.BangEqual, value: '!=', pos: start }); i += 2; continue;
    }
    if (ch === '<' && input[i + 1] === '=') {
      tokens.push({ type: TokenType.LessEqual, value: '<=', pos: start }); i += 2; continue;
    }
    if (ch === '>' && input[i + 1] === '=') {
      tokens.push({ type: TokenType.GreaterEqual, value: '>=', pos: start }); i += 2; continue;
    }

    // Single-character operators and delimiters — FIX: added '%' mapping
    const singles: Record<string, TokenType> = {
      '+': TokenType.Plus,
      '-': TokenType.Minus,
      '*': TokenType.Star,
      '/': TokenType.Slash,
      '%': TokenType.Percent,
      '<': TokenType.Less,
      '>': TokenType.Greater,
      '!': TokenType.Bang,
      '(': TokenType.LeftParen,
      ')': TokenType.RightParen,
      '[': TokenType.LeftBracket,
      ']': TokenType.RightBracket,
      '{': TokenType.LeftBrace,
      '}': TokenType.RightBrace,
      ',': TokenType.Comma,
      '.': TokenType.Dot,
    };

    const singleType = singles[ch];
    if (singleType) {
      tokens.push({ type: singleType, value: ch, pos: start });
      i++;
      continue;
    }

    throw new Error(`Unexpected character '${ch}' at position ${i}`);
  }

  tokens.push({ type: TokenType.EOF, value: '', pos: i });
  return tokens;
}

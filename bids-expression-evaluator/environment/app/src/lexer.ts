
import { Token, TokenType } from './types';

export function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;

  while (pos < input.length) {
    // Skip whitespace
    if (/\s/.test(input[pos])) {
      pos++;
      continue;
    }

    // Numbers (integer or floating point)
    if (/\d/.test(input[pos]) || (input[pos] === '.' && pos + 1 < input.length && /\d/.test(input[pos + 1]))) {
      let num = '';
      while (pos < input.length && /[\d.]/.test(input[pos])) {
        num += input[pos++];
      }
      tokens.push({ type: TokenType.Number, value: num, position: pos });
      continue;
    }

    // String literals (single or double quoted)
    if (input[pos] === '"' || input[pos] === "'") {
      const quote = input[pos++];
      let str = '';
      while (pos < input.length && input[pos] !== quote) {
        if (input[pos] === '\\') {
          pos++;
          str += input[pos++];
        } else {
          str += input[pos++];
        }
      }
      pos++; // closing quote
      tokens.push({ type: TokenType.String, value: str, position: pos });
      continue;
    }

    // Identifiers and keywords
    if (/[a-zA-Z_]/.test(input[pos])) {
      let ident = '';
      while (pos < input.length && /[a-zA-Z0-9_]/.test(input[pos])) {
        ident += input[pos++];
      }
      if (ident === 'true' || ident === 'false') {
        tokens.push({ type: TokenType.Boolean, value: ident, position: pos });
      } else if (ident === 'null') {
        tokens.push({ type: TokenType.Null, value: ident, position: pos });
      } else if (ident === 'in') {
        tokens.push({ type: TokenType.In, value: ident, position: pos });
      } else {
        tokens.push({ type: TokenType.Identifier, value: ident, position: pos });
      }
      continue;
    }

    // Two-character operators
    if (pos + 1 < input.length) {
      const two = input[pos] + input[pos + 1];
      if (two === '==') {
        tokens.push({ type: TokenType.EqualEqual, value: '==', position: pos });
        pos += 2;
        continue;
      }
      if (two === '<=') {
        tokens.push({ type: TokenType.LessEqual, value: '<=', position: pos });
        pos += 2;
        continue;
      }
      if (two === '>=') {
        tokens.push({ type: TokenType.GreaterEqual, value: '>=', position: pos });
        pos += 2;
        continue;
      }
      if (two === '&&') {
        tokens.push({ type: TokenType.And, value: '&&', position: pos });
        pos += 2;
        continue;
      }
      if (two === '||') {
        tokens.push({ type: TokenType.Or, value: '||', position: pos });
        pos += 2;
        continue;
      }
    }

    // Single-character tokens
    switch (input[pos]) {
      case '(':
        tokens.push({ type: TokenType.LeftParen, value: '(', position: pos });
        break;
      case ')':
        tokens.push({ type: TokenType.RightParen, value: ')', position: pos });
        break;
      case '[':
        tokens.push({ type: TokenType.LeftBracket, value: '[', position: pos });
        break;
      case ']':
        tokens.push({ type: TokenType.RightBracket, value: ']', position: pos });
        break;
      case '{':
        tokens.push({ type: TokenType.LeftBrace, value: '{', position: pos });
        break;
      case '}':
        tokens.push({ type: TokenType.RightBrace, value: '}', position: pos });
        break;
      case ',':
        tokens.push({ type: TokenType.Comma, value: ',', position: pos });
        break;
      case '.':
        tokens.push({ type: TokenType.Dot, value: '.', position: pos });
        break;
      case '+':
        tokens.push({ type: TokenType.Plus, value: '+', position: pos });
        break;
      case '-':
        tokens.push({ type: TokenType.Minus, value: '-', position: pos });
        break;
      case '*':
        tokens.push({ type: TokenType.Star, value: '*', position: pos });
        break;
      case '/':
        tokens.push({ type: TokenType.Slash, value: '/', position: pos });
        break;
      case '%':
        tokens.push({ type: TokenType.Percent, value: '%', position: pos });
        break;
      case '!':
        tokens.push({ type: TokenType.Bang, value: '!', position: pos });
        break;
      case '=':
        tokens.push({ type: TokenType.Equal, value: '=', position: pos });
        break;
      case '<':
        tokens.push({ type: TokenType.Less, value: '<', position: pos });
        break;
      case '>':
        tokens.push({ type: TokenType.Greater, value: '>', position: pos });
        break;
      default:
        throw new Error(`Unexpected character: ${input[pos]} at position ${pos}`);
    }
    pos++;
  }

  tokens.push({ type: TokenType.EOF, value: '', position: pos });
  return tokens;
}

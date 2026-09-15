import { Token, TokenType, Expr } from './types';

export function parse(tokens: Token[]): Expr {
  let pos = 0;

  function peek(): Token { return tokens[pos]; }
  function advance(): Token { return tokens[pos++]; }

  function expect(type: TokenType): Token {
    const t = peek();
    if (t.type !== type) {
      throw new Error(`Expected ${type} but got ${t.type} ('${t.value}') at position ${t.pos}`);
    }
    return advance();
  }

  function match(...types: TokenType[]): Token | null {
    if (types.includes(peek().type)) return advance();
    return null;
  }

  function parseExpr(): Expr {
    return parseOr();
  }

  function parseOr(): Expr {
    let left = parseAnd();
    while (match(TokenType.Or)) {
      left = { kind: 'binary', op: '||', left, right: parseAnd() };
    }
    return left;
  }

  function parseAnd(): Expr {
    let left = parseEquality();
    while (match(TokenType.And)) {
      left = { kind: 'binary', op: '&&', left, right: parseEquality() };
    }
    return left;
  }

  function parseEquality(): Expr {
    let left = parseComparison();
    let t: Token | null;
    while ((t = match(TokenType.EqualEqual, TokenType.BangEqual))) {
      left = { kind: 'binary', op: t.value, left, right: parseComparison() };
    }
    return left;
  }

  function parseComparison(): Expr {
    let left = parseIn();
    let t: Token | null;
    while ((t = match(TokenType.Less, TokenType.LessEqual, TokenType.Greater, TokenType.GreaterEqual))) {
      left = { kind: 'binary', op: t.value, left, right: parseIn() };
    }
    return left;
  }

  function parseIn(): Expr {
    let left = parseAddition();
    if (match(TokenType.In)) {
      left = { kind: 'binary', op: 'in', left, right: parseAddition() };
    }
    return left;
  }

  function parseAddition(): Expr {
    let left = parseMultiplication();
    let t: Token | null;
    while ((t = match(TokenType.Plus, TokenType.Minus))) {
      left = { kind: 'binary', op: t.value, left, right: parseMultiplication() };
    }
    return left;
  }

  function parseMultiplication(): Expr {
    let left = parseUnary();
    let t: Token | null;
    while ((t = match(TokenType.Star, TokenType.Slash, TokenType.Percent))) {
      left = { kind: 'binary', op: t.value, left, right: parseUnary() };
    }
    return left;
  }

  function parseUnary(): Expr {
    if (match(TokenType.Bang)) {
      return { kind: 'unary', op: '!', operand: parseUnary() };
    }
    if (match(TokenType.Minus)) {
      return { kind: 'unary', op: '-', operand: parseUnary() };
    }
    return parsePostfix();
  }

  function parsePostfix(): Expr {
    let expr = parsePrimary();
    while (true) {
      if (match(TokenType.Dot)) {
        const prop = expect(TokenType.Identifier);
        expr = { kind: 'member', object: expr, property: prop.value };
      } else if (peek().type === TokenType.LeftBracket) {
        advance();
        const idx = parseExpr();
        expect(TokenType.RightBracket);
        expr = { kind: 'index', object: expr, index: idx };
      } else {
        break;
      }
    }
    return expr;
  }

  function parsePrimary(): Expr {
    const t = peek();

    if (t.type === TokenType.Number) {
      advance();
      return { kind: 'literal', value: parseFloat(t.value) };
    }

    if (t.type === TokenType.String) {
      advance();
      return { kind: 'literal', value: t.value };
    }

    if (t.type === TokenType.True) {
      advance();
      return { kind: 'literal', value: true };
    }

    if (t.type === TokenType.False) {
      advance();
      return { kind: 'literal', value: false };
    }

    if (t.type === TokenType.Null) {
      advance();
      return { kind: 'literal', value: null };
    }

    if (t.type === TokenType.Identifier) {
      advance();
      // Check for function call
      if (peek().type === TokenType.LeftParen) {
        advance(); // consume '('
        const args: Expr[] = [];
        if (peek().type !== TokenType.RightParen) {
          args.push(parseExpr());
          while (match(TokenType.Comma)) {
            args.push(parseExpr());
          }
        }
        expect(TokenType.RightParen);
        return { kind: 'call', name: t.value, args };
      }
      return { kind: 'identifier', name: t.value };
    }

    if (t.type === TokenType.LeftParen) {
      advance();
      const expr = parseExpr();
      expect(TokenType.RightParen);
      return expr;
    }

    if (t.type === TokenType.LeftBracket) {
      advance();
      const elements: Expr[] = [];
      if (peek().type !== TokenType.RightBracket) {
        elements.push(parseExpr());
        while (match(TokenType.Comma)) {
          elements.push(parseExpr());
        }
      }
      expect(TokenType.RightBracket);
      return { kind: 'array', elements };
    }

    if (t.type === TokenType.LeftBrace) {
      advance();
      expect(TokenType.RightBrace);
      return { kind: 'object' };
    }

    throw new Error(`Unexpected token ${t.type} ('${t.value}') at position ${t.pos}`);
  }

  const result = parseExpr();
  if (peek().type !== TokenType.EOF) {
    const t = peek();
    throw new Error(`Unexpected token after expression: ${t.type} ('${t.value}') at position ${t.pos}`);
  }
  return result;
}

'use strict';

const { isCalendarDuration } = require('./units');

const T = {
  NUMBER: 'NUMBER',
  UNIT_CALENDAR: 'UNIT_CALENDAR',
  UNIT_UCUM: 'UNIT_UCUM',
  OP: 'OP',
  LPAREN: 'LPAREN',
  RPAREN: 'RPAREN',
  EOF: 'EOF'
};

/**
 * Tokenize a FHIRPath quantity expression string.
 */
function tokenize(input) {
  const tokens = [];
  let i = 0;
  while (i < input.length) {
    if (/\s/.test(input[i])) { i++; continue; }

    // Number (integer or decimal, possibly negative in unary position)
    if (/[0-9]/.test(input[i]) ||
        (input[i] === '-' && (tokens.length === 0 ||
         tokens[tokens.length - 1].type === T.OP ||
         tokens[tokens.length - 1].type === T.LPAREN))) {
      let start = i;
      if (input[i] === '-') i++;
      while (i < input.length && /[0-9]/.test(input[i])) i++;
      if (i < input.length && input[i] === '.') {
        i++;
        while (i < input.length && /[0-9]/.test(input[i])) i++;
      }
      tokens.push({ type: T.NUMBER, value: parseFloat(input.slice(start, i)) });
      continue;
    }

    // UCUM unit (single-quoted)
    if (input[i] === "'") {
      i++; // skip opening quote
      let start = i;
      while (i < input.length && /[a-zA-Z]/.test(input[i])) i++;
      const unit = input.slice(start, i);
      if (i >= input.length || input[i] !== "'") {
        throw new Error(`Unterminated UCUM unit at position ${start - 1}`);
      }
      i++; // skip closing quote
      tokens.push({ type: T.UNIT_UCUM, value: unit });
      continue;
    }

    // Multi-char operators
    if (input[i] === '!' && i + 1 < input.length && input[i + 1] === '=') {
      tokens.push({ type: T.OP, value: '!=' }); i += 2; continue;
    }
    if (input[i] === '<' && i + 1 < input.length && input[i + 1] === '=') {
      tokens.push({ type: T.OP, value: '<=' }); i += 2; continue;
    }
    if (input[i] === '>' && i + 1 < input.length && input[i + 1] === '=') {
      tokens.push({ type: T.OP, value: '>=' }); i += 2; continue;
    }

    // Single-char operators
    if ('+-*/=<>'.includes(input[i])) {
      tokens.push({ type: T.OP, value: input[i] }); i++; continue;
    }

    // Parentheses
    if (input[i] === '(') { tokens.push({ type: T.LPAREN }); i++; continue; }
    if (input[i] === ')') { tokens.push({ type: T.RPAREN }); i++; continue; }

    // Calendar duration unit (unquoted word)
    if (/[a-zA-Z]/.test(input[i])) {
      let start = i;
      while (i < input.length && /[a-zA-Z]/.test(input[i])) i++;
      const word = input.slice(start, i);
      if (isCalendarDuration(word)) {
        tokens.push({ type: T.UNIT_CALENDAR, value: word });
      } else {
        throw new Error(`Unknown identifier: ${word}`);
      }
      continue;
    }

    throw new Error(`Unexpected character: '${input[i]}' at position ${i}`);
  }
  tokens.push({ type: T.EOF });
  return tokens;
}

/**
 * Recursive descent parser.
 *
 * Precedence (low to high):
 *   comparison: = != < > <= >=
 *   additive:   + -
 *   multiplicative: * /
 *   unary: -
 *   atom: number, quantity, (expr)
 */
class Parser {
  constructor(tokens) {
    this.tokens = tokens;
    this.pos = 0;
  }
  peek() { return this.tokens[this.pos]; }
  advance() { return this.tokens[this.pos++]; }
  expect(type) {
    const t = this.advance();
    if (t.type !== type) throw new Error(`Expected ${type}, got ${t.type}`);
    return t;
  }

  parse() {
    const ast = this.expr();
    this.expect(T.EOF);
    return ast;
  }

  expr() { return this.comparison(); }

  comparison() {
    let left = this.addition();
    const t = this.peek();
    if (t.type === T.OP && ['=', '!=', '<', '>', '<=', '>='].includes(t.value)) {
      this.advance();
      const right = this.addition();
      return { type: 'binop', op: t.value, left, right };
    }
    return left;
  }

  addition() {
    let left = this.multiplication();
    while (this.peek().type === T.OP &&
           (this.peek().value === '+' || this.peek().value === '-')) {
      const op = this.advance().value;
      const right = this.multiplication();
      left = { type: 'binop', op, left, right };
    }
    return left;
  }

  multiplication() {
    let left = this.unary();
    while (this.peek().type === T.OP &&
           (this.peek().value === '*' || this.peek().value === '/')) {
      const op = this.advance().value;
      const right = this.unary();
      left = { type: 'binop', op, left, right };
    }
    return left;
  }

  unary() {
    if (this.peek().type === T.OP && this.peek().value === '-') {
      this.advance();
      const operand = this.atom();
      return { type: 'negate', operand };
    }
    return this.atom();
  }

  atom() {
    const t = this.peek();
    if (t.type === T.NUMBER) {
      this.advance();
      const next = this.peek();
      if (next.type === T.UNIT_CALENDAR || next.type === T.UNIT_UCUM) {
        this.advance();
        return {
          type: 'quantity', value: t.value, unit: next.value,
          ucum: next.type === T.UNIT_UCUM
        };
      }
      return { type: 'number', value: t.value };
    }
    if (t.type === T.LPAREN) {
      this.advance();
      const inner = this.expr();
      this.expect(T.RPAREN);
      return inner;
    }
    throw new Error(`Unexpected token: ${t.type} (${t.value})`);
  }
}

function parse(input) {
  return new Parser(tokenize(input)).parse();
}

module.exports = { parse, tokenize, T };

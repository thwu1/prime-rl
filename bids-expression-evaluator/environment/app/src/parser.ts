
import { Token, TokenType, ASTNode } from './types';
import { tokenize } from './lexer';

class Parser {
  private tokens: Token[];
  private pos: number = 0;

  constructor(tokens: Token[]) {
    this.tokens = tokens;
  }

  private peek(): Token {
    return this.tokens[this.pos];
  }

  private advance(): Token {
    const token = this.tokens[this.pos];
    this.pos++;
    return token;
  }

  private expect(type: TokenType): Token {
    const token = this.peek();
    if (token.type !== type) {
      throw new Error(
        `Expected ${type} but got ${token.type} (${token.value}) at position ${token.position}`
      );
    }
    return this.advance();
  }

  parse(): ASTNode {
    const node = this.parseExpression();
    if (this.peek().type !== TokenType.EOF) {
      throw new Error(`Unexpected token: ${this.peek().type} (${this.peek().value})`);
    }
    return node;
  }

  private parseExpression(): ASTNode {
    return this.parseOr();
  }

  private parseOr(): ASTNode {
    let left = this.parseAnd();
    while (this.peek().type === TokenType.Or) {
      this.advance();
      const right = this.parseAnd();
      left = { type: 'BinaryOp', operator: '||', left, right };
    }
    return left;
  }

  private parseAnd(): ASTNode {
    let left = this.parseEquality();
    while (this.peek().type === TokenType.And) {
      this.advance();
      const right = this.parseEquality();
      left = { type: 'BinaryOp', operator: '&&', left, right };
    }
    return left;
  }

  private parseEquality(): ASTNode {
    let left = this.parseComparison();
    while (
      this.peek().type === TokenType.EqualEqual ||
      this.peek().type === TokenType.BangEqual
    ) {
      const op = this.advance().value;
      const right = this.parseComparison();
      left = { type: 'BinaryOp', operator: op, left, right };
    }
    return left;
  }

  private parseComparison(): ASTNode {
    let left = this.parseAdditive();
    while (
      this.peek().type === TokenType.Less ||
      this.peek().type === TokenType.LessEqual ||
      this.peek().type === TokenType.Greater ||
      this.peek().type === TokenType.GreaterEqual
    ) {
      const op = this.advance().value;
      const right = this.parseAdditive();
      left = { type: 'BinaryOp', operator: op, left, right };
    }
    return left;
  }

  private parseAdditive(): ASTNode {
    let left = this.parseMultiplicative();
    while (
      this.peek().type === TokenType.Plus ||
      this.peek().type === TokenType.Minus
    ) {
      const op = this.advance().value;
      const right = this.parseMultiplicative();
      left = { type: 'BinaryOp', operator: op, left, right };
    }
    return left;
  }

  private parseMultiplicative(): ASTNode {
    let left = this.parseUnary();
    while (
      this.peek().type === TokenType.Star ||
      this.peek().type === TokenType.Slash
    ) {
      const op = this.advance().value;
      const right = this.parseUnary();
      left = { type: 'BinaryOp', operator: op, left, right };
    }
    return left;
  }

  private parseUnary(): ASTNode {
    if (this.peek().type === TokenType.Bang) {
      this.advance();
      const operand = this.parseUnary();
      return { type: 'UnaryOp', operator: '!', operand };
    }
    if (this.peek().type === TokenType.Minus) {
      this.advance();
      const operand = this.parseUnary();
      return { type: 'UnaryOp', operator: '-', operand };
    }
    return this.parsePostfix();
  }

  private parsePostfix(): ASTNode {
    let node = this.parsePrimary();

    while (true) {
      if (this.peek().type === TokenType.Dot) {
        this.advance();
        const prop = this.expect(TokenType.Identifier).value;
        node = { type: 'MemberAccess', object: node, property: prop };
      } else if (this.peek().type === TokenType.LeftBracket) {
        this.advance();
        const index = this.parseExpression();
        this.expect(TokenType.RightBracket);
        node = { type: 'IndexAccess', object: node, index };
      } else {
        break;
      }
    }

    return node;
  }

  private parsePrimary(): ASTNode {
    const token = this.peek();

    switch (token.type) {
      case TokenType.Number: {
        this.advance();
        return { type: 'NumberLiteral', value: parseFloat(token.value) };
      }

      case TokenType.String: {
        this.advance();
        return { type: 'StringLiteral', value: token.value };
      }

      case TokenType.Boolean: {
        this.advance();
        return { type: 'BooleanLiteral', value: token.value === 'true' };
      }

      case TokenType.Null: {
        this.advance();
        return { type: 'NullLiteral' };
      }

      case TokenType.Identifier: {
        const name = this.advance().value;
        // Function call
        if (this.peek().type === TokenType.LeftParen) {
          this.advance(); // consume '('
          const args: ASTNode[] = [];
          if (this.peek().type !== TokenType.RightParen) {
            args.push(this.parseExpression());
            while (this.peek().type === TokenType.Comma) {
              this.advance();
              args.push(this.parseExpression());
            }
          }
          this.expect(TokenType.RightParen);
          return { type: 'FunctionCall', name, args };
        }
        return { type: 'Identifier', name };
      }

      case TokenType.LeftParen: {
        this.advance();
        const expr = this.parseExpression();
        this.expect(TokenType.RightParen);
        return expr;
      }

      case TokenType.LeftBracket: {
        this.advance();
        const elements: ASTNode[] = [];
        if (this.peek().type !== TokenType.RightBracket) {
          elements.push(this.parseExpression());
          while (this.peek().type === TokenType.Comma) {
            this.advance();
            elements.push(this.parseExpression());
          }
        }
        this.expect(TokenType.RightBracket);
        return { type: 'ArrayLiteral', elements };
      }

      default:
        throw new Error(
          `Unexpected token: ${token.type} (${token.value}) at position ${token.position}`
        );
    }
  }
}

export function parse(input: string): ASTNode {
  const tokens = tokenize(input);
  const parser = new Parser(tokens);
  return parser.parse();
}

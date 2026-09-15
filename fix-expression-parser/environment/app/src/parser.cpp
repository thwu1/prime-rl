
#include "expr_lang.h"
#include <iostream>
#include <optional>

Parser::Parser(const std::string& input) : pos_(0) {
    Lexer lex(input);
    Token t;
    do {
        t = lex.next_token();
        tokens_.push_back(t);
    } while (t.type != TOK_EOF);
}

const Token& Parser::peek() const { return tokens_[pos_]; }
Token Parser::consume() { return tokens_[pos_++]; }

bool Parser::match(TokenType t) {
    if (peek().type == t) { pos_++; return true; }
    return false;
}

void Parser::expect(TokenType t) {
    if (!match(t))
        throw ParseError(peek().line, peek().col, "unexpected token");
}

std::string Parser::expect_ident() {
    if (peek().type != TOK_IDENT)
        throw ParseError(peek().line, peek().col, "expected identifier");
    return consume().str;
}

bool Parser::is_binop(TokenType t) const {
    return t == TOK_PLUS || t == TOK_MINUS || t == TOK_STAR ||
           t == TOK_SLASH || t == TOK_PERCENT ||
           t == TOK_LT || t == TOK_GT || t == TOK_LE ||
           t == TOK_GE || t == TOK_EQEQ || t == TOK_NEQ ||
           t == TOK_AND || t == TOK_OR;
}

long Parser::eval_binop(const Token& op, long left, long right) {
    switch (op.type) {
        case TOK_PLUS:    return left + right;
        case TOK_MINUS:   return left - right;
        case TOK_STAR:    return left * right;
        case TOK_SLASH:
            if (right == 0)
                throw ParseError(op.line, op.col, "division by zero");
            return left / right;
        case TOK_PERCENT:
            if (right == 0)
                throw ParseError(op.line, op.col, "modulo by zero");
            return left % right;
        case TOK_LT:     return (left < right) ? 1 : 0;
        case TOK_GT:     return (left > right) ? 1 : 0;
        case TOK_LE:     return (left <= right) ? 1 : 0;
        case TOK_GE:     return (left >= right) ? 1 : 0;
        case TOK_EQEQ:   return (left == right) ? 1 : 0;
        case TOK_NEQ:    return (left != right) ? 1 : 0;
        case TOK_AND:    return (left != 0 && right != 0) ? 1 : 0;
        case TOK_OR:     return (left != 0 || right != 0) ? 1 : 0;
        default:         return 0;
    }
}

void Parser::run() {
    while (peek().type != TOK_EOF) {
        if (peek().type == TOK_SEMI) {
            consume();
            continue;
        }
        long result = parse_expression();
        expect(TOK_SEMI);
        std::cout << result << "\n";
    }
}

long Parser::parse_expression() {
    if (peek().type == TOK_LET) {
        consume();
        std::string name = expect_ident();
        expect(TOK_EQ);
        long init = parse_expression();
        if (peek().type != TOK_IN)
            throw ParseError(peek().line, peek().col, "expected 'in'");
        consume();
        env_[name] = init;
        return parse_expression();
    }

    long left = parse_unary();

    if (is_binop(peek().type)) {
        Token op = consume();
        long right = parse_expression();
        return eval_binop(op, left, right);
    }

    if (match(TOK_QUESTION)) {
        long then_val = parse_expression();
        expect(TOK_COLON);
        long else_val = parse_expression();
        return left ? then_val : else_val;
    }

    return left;
}

long Parser::parse_unary() {
    if (match(TOK_MINUS)) return -parse_unary();
    if (match(TOK_PLUS))  return  parse_unary();
    if (match(TOK_NOT))   return  parse_unary() != 0 ? 0 : 1;
    return parse_primary();
}

long Parser::parse_primary() {
    if (peek().type == TOK_NUM) return consume().value;
    if (peek().type == TOK_TRUE)  { consume(); return 1; }
    if (peek().type == TOK_FALSE) { consume(); return 0; }
    if (peek().type == TOK_IDENT) {
        Token t = consume();
        std::optional<long> val;
        auto it = env_.find(t.str);
        if (it != env_.end()) val = it->second;
        if (!val)
            throw ParseError(t.line, t.col, "undefined variable: " + t.str);
        return *val;
    }
    if (match(TOK_LPAREN)) {
        long val = parse_expression();
        expect(TOK_RPAREN);
        return val;
    }
    throw ParseError(peek().line, peek().col, "expected expression");
}

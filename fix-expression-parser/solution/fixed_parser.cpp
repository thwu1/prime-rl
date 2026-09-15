
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

void Parser::run() {
    while (peek().type != TOK_EOF) {
        if (peek().type == TOK_SEMI) {
            consume();
            continue;
        }
        try {
            long result = parse_expression();
            expect(TOK_SEMI);
            std::cout << result << "\n";
        } catch (const ParseError& e) {
            std::cout << "ERROR " << e.line << ":" << e.col << "\n";
            while (peek().type != TOK_SEMI && peek().type != TOK_EOF)
                consume();
            if (peek().type == TOK_SEMI) consume();
        }
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

        auto old_it = env_.find(name);
        bool had_old = (old_it != env_.end());
        long old_val = had_old ? old_it->second : 0;
        env_[name] = init;

        long result;
        try {
            result = parse_expression();
        } catch (...) {
            if (had_old) env_[name] = old_val;
            else env_.erase(name);
            throw;
        }
        if (had_old) env_[name] = old_val;
        else env_.erase(name);
        return result;
    }
    return parse_ternary();
}

long Parser::parse_ternary() {
    long val = parse_logical_or();
    if (match(TOK_QUESTION)) {
        long then_val = parse_expression();
        expect(TOK_COLON);
        long else_val = parse_expression();
        val = val ? then_val : else_val;
    }
    return val;
}

long Parser::parse_logical_or() {
    long left = parse_logical_and();
    while (peek().type == TOK_OR) {
        consume();
        if (left != 0) {
            try { parse_logical_and(); } catch (const ParseError&) {}
            left = 1;
        } else {
            long right = parse_logical_and();
            left = (right != 0) ? 1 : 0;
        }
    }
    return left;
}

long Parser::parse_logical_and() {
    long left = parse_comparison();
    while (peek().type == TOK_AND) {
        consume();
        if (left == 0) {
            try { parse_comparison(); } catch (const ParseError&) {}
        } else {
            long right = parse_comparison();
            left = (right != 0) ? 1 : 0;
        }
    }
    return left;
}

long Parser::parse_comparison() {
    long left = parse_additive();
    while (peek().type == TOK_LT || peek().type == TOK_GT ||
           peek().type == TOK_LE || peek().type == TOK_GE ||
           peek().type == TOK_EQEQ || peek().type == TOK_NEQ) {
        Token op = consume();
        long right = parse_additive();
        switch (op.type) {
            case TOK_LT:   left = (left < right) ? 1 : 0; break;
            case TOK_GT:   left = (left > right) ? 1 : 0; break;
            case TOK_LE:   left = (left <= right) ? 1 : 0; break;
            case TOK_GE:   left = (left >= right) ? 1 : 0; break;
            case TOK_EQEQ: left = (left == right) ? 1 : 0; break;
            case TOK_NEQ:  left = (left != right) ? 1 : 0; break;
            default: break;
        }
    }
    return left;
}

long Parser::parse_additive() {
    long left = parse_multiplicative();
    while (peek().type == TOK_PLUS || peek().type == TOK_MINUS) {
        Token op = consume();
        long right = parse_multiplicative();
        if (op.type == TOK_PLUS) left += right;
        else left -= right;
    }
    return left;
}

long Parser::parse_multiplicative() {
    long left = parse_unary();
    while (peek().type == TOK_STAR || peek().type == TOK_SLASH ||
           peek().type == TOK_PERCENT) {
        Token op = consume();
        long right = parse_unary();
        if (op.type == TOK_STAR) {
            left *= right;
        } else if (op.type == TOK_SLASH) {
            if (right == 0)
                throw ParseError(op.line, op.col, "division by zero");
            left /= right;
        } else {
            if (right == 0)
                throw ParseError(op.line, op.col, "modulo by zero");
            left %= right;
        }
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

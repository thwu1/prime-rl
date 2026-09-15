
#ifndef EXPR_LANG_H
#define EXPR_LANG_H

#include <string>
#include <vector>
#include <map>
#include <stdexcept>

enum TokenType {
    TOK_NUM, TOK_TRUE, TOK_FALSE, TOK_IDENT,
    TOK_PLUS, TOK_MINUS, TOK_STAR, TOK_SLASH, TOK_PERCENT,
    TOK_LT, TOK_GT, TOK_LE, TOK_GE, TOK_EQEQ, TOK_NEQ,
    TOK_AND, TOK_OR, TOK_NOT,
    TOK_LPAREN, TOK_RPAREN, TOK_QUESTION, TOK_COLON,
    TOK_EQ, TOK_LET, TOK_IN,
    TOK_SEMI, TOK_EOF, TOK_ERR
};

struct Token {
    TokenType type;
    long value;
    std::string str;
    int line, col;
};

class ParseError : public std::runtime_error {
public:
    int line, col;
    ParseError(int l, int c, const std::string& msg)
        : std::runtime_error(msg), line(l), col(c) {}
};

class Lexer {
    const std::string& src_;
    size_t pos_;
    int line_, col_;
    void advance();
    void skip_ws();
public:
    explicit Lexer(const std::string& s);
    Token next_token();
};

class Parser {
    std::vector<Token> tokens_;
    size_t pos_;
    std::map<std::string, long> env_;

    const Token& peek() const;
    Token consume();
    bool match(TokenType t);
    void expect(TokenType t);
    std::string expect_ident();

    long parse_expression();
    long parse_ternary();
    long parse_logical_or();
    long parse_logical_and();
    long parse_comparison();
    long parse_additive();
    long parse_multiplicative();
    long parse_unary();
    long parse_primary();

public:
    explicit Parser(const std::string& input);
    void run();
};

#endif // EXPR_LANG_H

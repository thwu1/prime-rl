
#include "expr_lang.h"
#include <cctype>

Lexer::Lexer(const std::string& s) : src_(s), pos_(0), line_(1), col_(1) {}

void Lexer::advance() {
    if (pos_ < src_.size()) {
        if (src_[pos_] == '\n') { line_++; col_ = 1; }
        else col_++;
        pos_++;
    }
}

void Lexer::skip_ws() {
    while (pos_ < src_.size()) {
        if (src_[pos_] == '#') {
            while (pos_ < src_.size() && src_[pos_] != '\n') advance();
        } else if (std::isspace(static_cast<unsigned char>(src_[pos_]))) {
            advance();
        } else {
            break;
        }
    }
}

Token Lexer::next_token() {
    skip_ws();
    if (pos_ >= src_.size()) return {TOK_EOF, 0, "", line_, col_};

    int l = line_, c = col_;
    char ch = src_[pos_];

    if (std::isdigit(ch)) {
        long val = 0;
        std::string s;
        while (pos_ < src_.size() && std::isdigit(src_[pos_])) {
            val = val * 10 + (src_[pos_] - '0');
            s += src_[pos_];
            advance();
        }
        return {TOK_NUM, val, s, l, c};
    }

    if (std::isalpha(ch) || ch == '_') {
        std::string s;
        while (pos_ < src_.size() && (std::isalnum(src_[pos_]) || src_[pos_] == '_')) {
            s += src_[pos_];
            advance();
        }
        if (s == "let")   return {TOK_LET, 0, s, l, c};
        if (s == "in")    return {TOK_IN, 0, s, l, c};
        if (s == "true")  return {TOK_TRUE, 1, s, l, c};
        if (s == "false") return {TOK_FALSE, 0, s, l, c};
        return {TOK_IDENT, 0, s, l, c};
    }

    advance();
    switch (ch) {
        case '+': return {TOK_PLUS, 0, "+", l, c};
        case '-': return {TOK_MINUS, 0, "-", l, c};
        case '*': return {TOK_STAR, 0, "*", l, c};
        case '/': return {TOK_SLASH, 0, "/", l, c};
        case '%': return {TOK_PERCENT, 0, "%", l, c};
        case '(': return {TOK_LPAREN, 0, "(", l, c};
        case ')': return {TOK_RPAREN, 0, ")", l, c};
        case '?': return {TOK_QUESTION, 0, "?", l, c};
        case ':': return {TOK_COLON, 0, ":", l, c};
        case ';': return {TOK_SEMI, 0, ";", l, c};
        case '<':
            if (pos_ < src_.size() && src_[pos_] == '=') {
                advance(); return {TOK_LE, 0, "<=", l, c};
            }
            return {TOK_LT, 0, "<", l, c};
        case '>':
            if (pos_ < src_.size() && src_[pos_] == '=') {
                advance(); return {TOK_GE, 0, ">=", l, c};
            }
            return {TOK_GT, 0, ">", l, c};
        case '=':
            if (pos_ < src_.size() && src_[pos_] == '=') {
                advance(); return {TOK_EQEQ, 0, "==", l, c};
            }
            return {TOK_EQ, 0, "=", l, c};
        case '!':
            if (pos_ < src_.size() && src_[pos_] == '=') {
                advance(); return {TOK_NEQ, 0, "!=", l, c};
            }
            return {TOK_NOT, 0, "!", l, c};
        case '&':
            if (pos_ < src_.size() && src_[pos_] == '&') {
                advance(); return {TOK_AND, 0, "&&", l, c};
            }
            return {TOK_ERR, 0, "&", l, c};
        case '|':
            if (pos_ < src_.size() && src_[pos_] == '|') {
                advance(); return {TOK_OR, 0, "||", l, c};
            }
            return {TOK_ERR, 0, "|", l, c};
        default:
            return {TOK_ERR, 0, std::string(1, ch), l, c};
    }
}

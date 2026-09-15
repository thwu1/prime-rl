
// Expression Language Interpreter
//
// Reads semicolon-delimited expressions from stdin.
// Outputs one result per expression to stdout.

#include <iostream>
#include <string>
#include <stdexcept>
#include <cctype>
#include <vector>
#include <map>

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

public:
    Lexer(const std::string& s) : src_(s), pos_(0), line_(1), col_(1) {}

    Token next_token() {
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
            case '!': return {TOK_NOT, 0, "!", l, c};
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

private:
    void advance() {
        if (pos_ < src_.size()) {
            if (src_[pos_] == '\n') { line_++; col_ = 1; }
            else col_++;
            pos_++;
        }
    }

    void skip_ws() {
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
};

class Parser {
    std::vector<Token> tokens_;
    size_t pos_;
    std::map<std::string, long> env_;

public:
    Parser(const std::string& input) : pos_(0) {
        Lexer lex(input);
        Token t;
        do {
            t = lex.next_token();
            tokens_.push_back(t);
        } while (t.type != TOK_EOF);
    }

    void run() {
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

private:
    const Token& peek() const { return tokens_[pos_]; }
    Token consume() { return tokens_[pos_++]; }

    bool match(TokenType t) {
        if (peek().type == t) { pos_++; return true; }
        return false;
    }

    void expect(TokenType t) {
        if (!match(t)) {
            throw ParseError(peek().line, peek().col, "unexpected token");
        }
    }

    std::string expect_ident() {
        if (peek().type != TOK_IDENT) {
            throw ParseError(peek().line, peek().col, "expected identifier");
        }
        return consume().str;
    }

    bool is_binop(TokenType t) const {
        return t == TOK_PLUS || t == TOK_MINUS || t == TOK_STAR ||
               t == TOK_SLASH || t == TOK_PERCENT ||
               t == TOK_LT || t == TOK_GT || t == TOK_LE ||
               t == TOK_GE || t == TOK_EQEQ || t == TOK_NEQ ||
               t == TOK_AND || t == TOK_OR;
    }

    long parse_expression() {
        if (peek().type == TOK_LET) {
            consume();
            std::string name = expect_ident();
            expect(TOK_EQ);
            long init = parse_expression();
            if (peek().type != TOK_IN) {
                throw ParseError(peek().line, peek().col, "expected 'in'");
            }
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

    long eval_binop(const Token& op, long left, long right) {
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

    long parse_unary() {
        if (match(TOK_MINUS)) return -parse_unary();
        if (match(TOK_PLUS))  return  parse_unary();
        if (match(TOK_NOT))   return  parse_unary() != 0 ? 0 : 1;
        return parse_primary();
    }

    long parse_primary() {
        if (peek().type == TOK_NUM) {
            return consume().value;
        }
        if (peek().type == TOK_TRUE) {
            consume();
            return 1;
        }
        if (peek().type == TOK_FALSE) {
            consume();
            return 0;
        }
        if (peek().type == TOK_IDENT) {
            Token t = consume();
            auto it = env_.find(t.str);
            if (it == env_.end()) {
                throw ParseError(t.line, t.col, "undefined variable: " + t.str);
            }
            return it->second;
        }
        if (match(TOK_LPAREN)) {
            long val = parse_expression();
            expect(TOK_RPAREN);
            return val;
        }
        throw ParseError(peek().line, peek().col, "expected expression");
    }
};

int main() {
    std::string input;
    std::string line;
    while (std::getline(std::cin, line)) {
        input += line + "\n";
    }

    try {
        Parser parser(input);
        parser.run();
    } catch (const ParseError& e) {
        std::cerr << "Error at " << e.line << ":" << e.col
                  << ": " << e.what() << std::endl;
        return 1;
    }

    return 0;
}

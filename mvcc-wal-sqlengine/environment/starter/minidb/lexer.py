from .types import Token, TokenType

KEYWORDS = {
    'create': TokenType.CREATE, 'table': TokenType.TABLE,
    'insert': TokenType.INSERT, 'into': TokenType.INTO,
    'values': TokenType.VALUES, 'select': TokenType.SELECT,
    'from': TokenType.FROM, 'where': TokenType.WHERE,
    'update': TokenType.UPDATE, 'set': TokenType.SET,
    'delete': TokenType.DELETE, 'and': TokenType.AND,
    'or': TokenType.OR, 'not': TokenType.NOT,
    'null': TokenType.NULL, 'true': TokenType.TRUE,
    'false': TokenType.FALSE, 'int': TokenType.INT_TYPE,
    'text': TokenType.TEXT_TYPE, 'boolean': TokenType.BOOLEAN_TYPE,
}


def tokenize(sql: str) -> list:
    tokens = []
    i = 0
    while i < len(sql):
        if sql[i].isspace():
            i += 1
            continue
        c = sql[i]
        if c == '(':
            tokens.append(Token(TokenType.LPAREN, c)); i += 1
        elif c == ')':
            tokens.append(Token(TokenType.RPAREN, c)); i += 1
        elif c == ',':
            tokens.append(Token(TokenType.COMMA, c)); i += 1
        elif c == ';':
            tokens.append(Token(TokenType.SEMICOLON, c)); i += 1
        elif c == '*':
            tokens.append(Token(TokenType.STAR, c)); i += 1
        elif c == '=' :
            tokens.append(Token(TokenType.EQ, c)); i += 1
        elif c == '!' and i + 1 < len(sql) and sql[i + 1] == '=':
            tokens.append(Token(TokenType.NEQ, '!=')); i += 2
        elif c == '<':
            if i + 1 < len(sql) and sql[i + 1] == '=':
                tokens.append(Token(TokenType.LTE, '<=')); i += 2
            elif i + 1 < len(sql) and sql[i + 1] == '>':
                tokens.append(Token(TokenType.NEQ, '<>')); i += 2
            else:
                tokens.append(Token(TokenType.LT, '<')); i += 1
        elif c == '>':
            if i + 1 < len(sql) and sql[i + 1] == '=':
                tokens.append(Token(TokenType.GTE, '>=')); i += 2
            else:
                tokens.append(Token(TokenType.GT, '>')); i += 1
        elif c == "'":
            j = i + 1
            while j < len(sql) and sql[j] != "'":
                j += 1
            if j >= len(sql):
                raise SyntaxError(f"Unterminated string at position {i}")
            tokens.append(Token(TokenType.STRING_LIT, sql[i + 1:j]))
            i = j + 1
        elif c.isdigit() or (c == '-' and i + 1 < len(sql) and sql[i + 1].isdigit()):
            j = i + 1 if c == '-' else i
            while j < len(sql) and sql[j].isdigit():
                j += 1
            tokens.append(Token(TokenType.INTEGER_LIT, sql[i:j]))
            i = j
        elif c.isalpha() or c == '_':
            j = i
            while j < len(sql) and (sql[j].isalnum() or sql[j] == '_'):
                j += 1
            word = sql[i:j]
            tt = KEYWORDS.get(word.lower())
            if tt:
                tokens.append(Token(tt, word.lower()))
            else:
                tokens.append(Token(TokenType.IDENT, word))
            i = j
        else:
            raise SyntaxError(f"Unexpected character '{c}' at position {i}")
    tokens.append(Token(TokenType.EOF, ''))
    return tokens

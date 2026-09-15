#!/usr/bin/env python3
"""PLY LALR(1) parser for the IMP imperative language.

Uses a unified 'expr' nonterminal for both arithmetic and boolean
expressions to avoid the aexp/bexp ambiguity in LALR(1) parsing.
The operator token classes (mathop, relop, logop) are disjoint,
so the parser can discriminate after seeing LPAREN expr <operator>.
"""

import ply.yacc as yacc
from imp_lexer import tokens, lexer as _base_lexer  # noqa: F401 (tokens needed by PLY)


# ---- Program / Statement list ----

def p_program(p):
    'program : stmt_list'
    p[0] = p[1]


def p_stmt_list_empty(p):
    'stmt_list :'
    p[0] = []


def p_stmt_list(p):
    'stmt_list : stmt SEMI stmt_list'
    p[0] = [p[1]] + p[3]


# ---- Statements ----

def p_stmt_int(p):
    'stmt : INT ID'
    p[0] = ('int', p[2])


def p_stmt_assign(p):
    'stmt : ID ASSIGN expr'
    p[0] = ('assign', p[1], p[3])


def p_stmt_if(p):
    'stmt : IF LPAREN expr RPAREN LBRACE stmt_list RBRACE ELSE LBRACE stmt_list RBRACE'
    p[0] = ('if', p[3], p[6], p[10])


def p_stmt_while(p):
    'stmt : WHILE LPAREN expr RPAREN LBRACE stmt_list RBRACE'
    p[0] = ('while', p[3], p[6])


def p_stmt_break(p):
    'stmt : BREAK'
    p[0] = ('break',)


def p_stmt_continue(p):
    'stmt : CONTINUE'
    p[0] = ('continue',)


def p_stmt_halt(p):
    'stmt : HALT'
    p[0] = ('halt',)


# ---- Expressions (unified aexp + bexp) ----

def p_expr_num(p):
    'expr : NUMBER'
    p[0] = ('num', p[1])


def p_expr_id(p):
    'expr : ID'
    p[0] = ('var', p[1])


def p_expr_true(p):
    'expr : TRUE'
    p[0] = ('bool', True)


def p_expr_false(p):
    'expr : FALSE'
    p[0] = ('bool', False)


def p_expr_binop(p):
    'expr : LPAREN expr mathop expr RPAREN'
    p[0] = ('binop', p[3], p[2], p[4])


def p_expr_relop(p):
    'expr : LPAREN expr relop expr RPAREN'
    p[0] = ('relop', p[3], p[2], p[4])


def p_expr_logop(p):
    'expr : LPAREN expr logop expr RPAREN'
    p[0] = ('logop', p[3], p[2], p[4])


def p_expr_not(p):
    'expr : LPAREN NOT expr RPAREN'
    p[0] = ('not', p[3])


def p_expr_unary_neg(p):
    'expr : LPAREN MINUS expr RPAREN'
    p[0] = ('unary', '-', p[3])


def p_expr_unary_pos(p):
    'expr : LPAREN PLUS expr RPAREN'
    p[0] = ('unary', '+', p[3])


# ---- Operator groups ----

def p_mathop(p):
    '''mathop : PLUS
              | MINUS
              | TIMES
              | DIVIDE
              | MOD'''
    p[0] = p[1]


def p_relop(p):
    '''relop : LT
             | LEQ
             | GT
             | GEQ
             | EQ
             | NEQ'''
    p[0] = p[1]


def p_logop(p):
    '''logop : AND
             | OR'''
    p[0] = p[1]


def p_error(p):
    if p:
        raise SyntaxError(
            f"Syntax error at token {p.type} ('{p.value}') line {p.lineno}"
        )
    else:
        raise SyntaxError("Syntax error at end of input")


parser = yacc.yacc()


def parse(source):
    """Parse IMP source code and return the AST."""
    return parser.parse(source, lexer=_base_lexer.clone())

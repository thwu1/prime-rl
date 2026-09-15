#!/usr/bin/env python3
"""PLY lexer for the IMP imperative language."""

import ply.lex as lex

reserved = {
    'int': 'INT',
    'if': 'IF',
    'else': 'ELSE',
    'while': 'WHILE',
    'LOOP': 'LOOP_KW',
    'halt': 'HALT',
    'continue': 'CONTINUE',
    'break': 'BREAK',
    'true': 'TRUE',
    'false': 'FALSE',
    'LE': 'LE_KW',
}

tokens = [
    'NUMBER', 'ID',
    'PLUS', 'MINUS', 'TIMES', 'DIVIDE', 'MOD',
    'LT', 'LEQ', 'GT', 'GEQ', 'EQ', 'NEQ',
    'AND', 'OR', 'NOT',
    'ASSIGN',
    'LPAREN', 'RPAREN', 'LBRACE', 'RBRACE',
    'SEMI',
] + list(reserved.values())

# Multi-character tokens (PLY sorts string tokens by length, longest first)
t_AND = r'&&'
t_OR = r'\|\|'
t_NEQ = r'!='
t_EQ = r'=='
t_LEQ = r'<='
t_GEQ = r'>='

# Single-character tokens
t_LT = r'<'
t_GT = r'>'
t_NOT = r'!'
t_PLUS = r'\+'
t_MINUS = r'-'
t_TIMES = r'\*'
t_DIVIDE = r'/'
t_MOD = r'%'
t_ASSIGN = r'='
t_SEMI = r';'
t_LPAREN = r'\('
t_RPAREN = r'\)'
t_LBRACE = r'\{'
t_RBRACE = r'\}'


def t_NUMBER(t):
    r'\d+'
    t.value = int(t.value)
    return t


def t_ID(t):
    r'[a-zA-Z][a-zA-Z0-9]*'
    t.type = reserved.get(t.value, 'ID')
    return t


t_ignore = ' \t\n\r'


def t_error(t):
    raise SyntaxError(
        f"Illegal character '{t.value[0]}' at position {t.lexpos}"
    )


lexer = lex.lex()

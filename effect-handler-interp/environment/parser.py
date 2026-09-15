
"""
Parser for the effect handler language.
Uses lark for parsing and ASTBuilder for AST construction.
"""

import os
from lark import Lark
from transform import ASTBuilder

_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_dir, 'grammar.lark')) as f:
    _grammar = f.read()

_parser = Lark(_grammar, parser='earley')
_builder = ASTBuilder()


def parse(source):
    """Parse source code into an AST Program node."""
    tree = _parser.parse(source)
    return _builder.transform(tree)

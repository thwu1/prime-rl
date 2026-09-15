#!/usr/bin/env python3

"""Fix scanner.l and parser.y source files."""

import re

# ============================================================
# Fix scanner.l: add %option noyywrap
# ============================================================
with open('/app/scanner.l', 'r') as f:
    content = f.read()

if '%option noyywrap' not in content:
    # Add %option noyywrap after the existing %option line
    content = content.replace('%option yylineno', '%option yylineno\n%option noyywrap')

with open('/app/scanner.l', 'w') as f:
    f.write(content)

# ============================================================
# Fix parser.y: add operator precedence declarations
# ============================================================
with open('/app/parser.y', 'r') as f:
    content = f.read()

prec_decls = """%left OR
%left AND
%left EQ NEQ
%left LT GT LEQ GEQ
%left PLUS MINUS
%left STAR SLASH PERCENT
%nonassoc UMINUS UNOT
"""

# Insert precedence declarations after %type line
content = content.replace(
    '%type <sval> expr\n',
    '%type <sval> expr\n\n' + prec_decls + '\n'
)

# Add %prec UMINUS to unary minus rule
content = content.replace(
    '| MINUS expr {',
    '| MINUS expr %prec UMINUS {'
)

# Add %prec UNOT to unary not rule
content = content.replace(
    '| NOT expr {',
    '| NOT expr %prec UNOT {'
)

with open('/app/parser.y', 'w') as f:
    f.write(content)

print("Sources fixed successfully.")

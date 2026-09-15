#!/bin/bash

# Restore provided task files from backup in case /app/ was remounted
cp -f /opt/cool_task/lex_main.c /app/lex_main.c 2>/dev/null || true
cp -f /opt/cool_task/json_escape.h /app/json_escape.h 2>/dev/null || true
cp -f /opt/cool_task/cool_parser.py /app/cool_parser.py 2>/dev/null || true
cp -f /opt/cool_task/ast_format.md /app/ast_format.md 2>/dev/null || true
cp -f /opt/cool_task/cool_type_rules.md /app/cool_type_rules.md 2>/dev/null || true
cp -f /opt/cool_task/token_spec.md /app/token_spec.md 2>/dev/null || true
cp -rf /opt/cool_task/programs /app/ 2>/dev/null || true

# Copy solution files
cp /solution/cool.l /app/cool.l
cp /solution/Makefile /app/Makefile
cp /solution/type_checker.py /app/type_checker.py

# Build the Flex lexer
cd /app
make

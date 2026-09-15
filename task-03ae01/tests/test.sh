#!/bin/bash

pip3 install pytest==8.3.4 -q

# Restore provided task files from backup in case /app/ was remounted
cp -f /opt/cool_task/lex_main.c /app/lex_main.c 2>/dev/null || true
cp -f /opt/cool_task/json_escape.h /app/json_escape.h 2>/dev/null || true
cp -f /opt/cool_task/cool_parser.py /app/cool_parser.py 2>/dev/null || true
cp -f /opt/cool_task/ast_format.md /app/ast_format.md 2>/dev/null || true
cp -f /opt/cool_task/cool_type_rules.md /app/cool_type_rules.md 2>/dev/null || true
cp -f /opt/cool_task/token_spec.md /app/token_spec.md 2>/dev/null || true
cp -rf /opt/cool_task/programs /app/ 2>/dev/null || true

cd /app

# Build the Flex lexer if Makefile and cool.l exist
if [ -f Makefile ] && [ -f cool.l ]; then
    make 2>&1
fi

python3 -m pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE

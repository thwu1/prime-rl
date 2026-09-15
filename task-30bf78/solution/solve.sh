#!/bin/bash

set -e

cd /app

# Install ANTLR4 Python runtime
pip3 install antlr4-python3-runtime==4.13.2 -q

# Generate Python lexer/parser/visitor from the Lox ANTLR4 grammar
make generate

# Deploy the transpiler
cp /solution/transpiler.py /app/transpile.py

#!/usr/bin/env bash

set -euo pipefail

# Fix CMakeLists.txt
cp /solution/fixed_cmake.txt /app/CMakeLists.txt

# Fix header (add new parse method declarations)
cp /solution/fixed_header.h /app/include/expr_lang.h

# Fix lexer (add != tokenization)
cp /solution/fixed_lexer.cpp /app/src/lexer.cpp

# Fix parser (precedence chain, short-circuit, scope cleanup, error recovery)
cp /solution/fixed_parser.cpp /app/src/parser.cpp

# Build
cmake -B /app/build -S /app
cmake --build /app/build

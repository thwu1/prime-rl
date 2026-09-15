#!/bin/bash
#
# Build the flex-generated DDL tokenizer into a shared library.
# Requires: flex, gcc

set -e
cd /app

# Generate C source from flex specification
flex -o ddl_lex.c ddl_lexer.l

# Compile into position-independent shared library
gcc -shared -fPIC -O2 -o libddl_lexer.so ddl_lex.c

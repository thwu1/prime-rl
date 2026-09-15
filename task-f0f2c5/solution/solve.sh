#!/bin/bash

# Copy solution files to /app/
cp /solution/ddl_lexer.l /app/ddl_lexer.l
cp /solution/build.sh /app/build.sh
cp /solution/ddl_interpreter.py /app/ddl_interpreter.py
chmod +x /app/build.sh

# Build the flex tokenizer shared library
bash /app/build.sh

#!/bin/bash

set -e

cd /app

# Step 1: Install the correct, conflict-free parser grammar
cp /solution/correct_parser.mly /app/lib/parser.mly

# Step 2: Update lib/dune to use --table mode and depend on menhirLib
cat > /app/lib/dune << 'DUNEFILE'
(library
 (name miniml)
 (libraries menhirLib))

(menhir
 (modules parser)
 (flags --table))

(ocamllex lexer)
DUNEFILE

# Step 3: Install the incremental API driver
cp /solution/correct_main.ml /app/bin/main.ml

# Step 4: Build the project (verifies grammar is conflict-free)
dune build 2>&1

# Step 5: Generate the complete .messages file
menhir --list-errors /app/lib/parser.mly > /tmp/raw_messages.txt

# Step 6: Replace placeholder messages with meaningful text
python3 /solution/gen_messages.py < /tmp/raw_messages.txt > /app/lib/errors.messages

# Step 7: Verify the messages file is complete
menhir --list-errors /app/lib/parser.mly > /tmp/complete_check.txt
menhir --compare-errors /tmp/complete_check.txt \
       --compare-errors /app/lib/errors.messages \
       /app/lib/parser.mly

echo "Solution applied successfully."

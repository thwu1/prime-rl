#!/bin/bash
# Reference interpreter: runs an ANF lambda calculus program through GNU Guile Scheme
# Usage: /app/reference/run_guile.sh <program.scm>
#
# Since the ANF lambda calculus is a subset of standard Scheme, Guile can
# evaluate these programs directly. Use this to verify expected results.
if [ -z "$1" ]; then
    echo "Usage: $0 <program.scm>"
    exit 1
fi
{
  echo "(define call/cc call-with-current-continuation)"
  printf "(display\n"
  cat "$1"
  printf "\n)\n(newline)\n"
} | guile-3.0 --no-auto-compile -

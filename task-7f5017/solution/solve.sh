#!/bin/bash

# Install the complete compiler solution
cp /solution/compile_solution.rkt /app/compile.rkt

cd /app

# Verify the solution compiles a simple program
echo "(program 42)" > /tmp/test_simple.scm
racket main.rkt -f /tmp/test_simple.scm 2>&1
RESULT=$(echo "0" | ./output 2>/dev/null)
if [ "$RESULT" = "42" ]; then
    echo "Solution verified: simple program compiles and runs correctly"
else
    echo "Warning: simple test returned '$RESULT' instead of '42'"
fi

# Verify a function call program
echo "(program (define (f x) (+ x 1)) (f 41))" > /tmp/test_func.scm
racket main.rkt -f /tmp/test_func.scm 2>&1
RESULT=$(echo "0" | ./output 2>/dev/null)
if [ "$RESULT" = "42" ]; then
    echo "Solution verified: function program compiles and runs correctly"
else
    echo "Warning: function test returned '$RESULT' instead of '42'"
fi

# Verify a closure program
echo "(program (define (f x) (lambda (y) (+ x y))) ((f 10) 32))" > /tmp/test_closure.scm
racket main.rkt -f /tmp/test_closure.scm 2>&1
RESULT=$(echo "0" | ./output 2>/dev/null)
if [ "$RESULT" = "42" ]; then
    echo "Solution verified: closure program compiles and runs correctly"
else
    echo "Warning: closure test returned '$RESULT' instead of '42'"
fi

rm -f /tmp/test_simple.scm /tmp/test_func.scm /tmp/test_closure.scm

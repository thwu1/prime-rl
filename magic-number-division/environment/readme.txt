Division Optimization Audit & Remediation
==========================================

Binary:  /app/challenge
Spec:    /app/spec.json

A developer attempted to hand-optimize 8 integer division/modulo functions
by replacing standard div/idiv instructions with magic-number multiplication
sequences (the same optimization that modern compilers perform at -O2).

The binary was compiled from the developer's code and stripped.

Usage: ./challenge <func_index> <value>
  func_index: integer 0-7, selects a function
  value: integer input

Prints the integer result of applying the selected function to the input.

The specification (spec.json) documents what each function is INTENDED to
compute.  Not all functions may match their specification.

Operations:
  sdiv  = signed 32-bit integer division (C truncation semantics)
  udiv  = unsigned 32-bit integer division
  smod  = signed 32-bit integer modulo (result has sign of dividend)
  umod  = unsigned 32-bit integer modulo

Severity Criteria:
  critical — more than 25% of the full signed 32-bit input space affected
  high     — between 1% and 25% of inputs affected
  medium   — between 0.01% and 1% of inputs affected
  low      — less than 0.01% of inputs affected

The "input space" is the set of all 2^32 values representable as a signed
32-bit integer: [-2^31, 2^31 - 1].  For unsigned operations, inputs are
reinterpreted as unsigned but the input VALUE is still drawn from this
signed range.  The error_count is the number of inputs in this range where
the function's actual output differs from the specified output.

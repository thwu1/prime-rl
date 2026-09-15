
import type { Expect, Equal } from 'type-testing';
import type { Parse } from '../src/parser';

// Single-digit PUSH
type test_parse_push_single = Expect<Equal<
  Parse<'PUSH 5'>,
  [['PUSH', 5]]
>>;

// Multi-digit PUSH
type test_parse_push_multi = Expect<Equal<
  Parse<'PUSH 42'>,
  [['PUSH', 42]]
>>;

type test_parse_push_10 = Expect<Equal<
  Parse<'PUSH 10'>,
  [['PUSH', 10]]
>>;

// Multiple instructions
type test_parse_add_program = Expect<Equal<
  Parse<'PUSH 3 PUSH 4 ADD'>,
  [['PUSH', 3], ['PUSH', 4], ['ADD']]
>>;

// All stack operations
type test_parse_all_ops = Expect<Equal<
  Parse<'PUSH 1 DUP SWAP POP OVER ROT'>,
  [['PUSH', 1], ['DUP'], ['SWAP'], ['POP'], ['OVER'], ['ROT']]
>>;

// Multi-digit in complex program
type test_parse_complex = Expect<Equal<
  Parse<'PUSH 10 PUSH 3 SUB'>,
  [['PUSH', 10], ['PUSH', 3], ['SUB']]
>>;

// Arithmetic operations
type test_parse_mul = Expect<Equal<
  Parse<'PUSH 6 PUSH 7 MUL'>,
  [['PUSH', 6], ['PUSH', 7], ['MUL']]
>>;

// Parse IFZERO, ELSE, ENDIF conditional instructions
type test_parse_ifzero = Expect<Equal<
  Parse<'PUSH 1 IFZERO PUSH 2 ENDIF'>,
  [['PUSH', 1], ['IFZERO'], ['PUSH', 2], ['ENDIF']]
>>;

type test_parse_else = Expect<Equal<
  Parse<'PUSH 0 IFZERO PUSH 1 ELSE PUSH 2 ENDIF'>,
  [['PUSH', 0], ['IFZERO'], ['PUSH', 1], ['ELSE'], ['PUSH', 2], ['ENDIF']]
>>;

// Multi-digit with conditionals
type test_parse_conditional_multidigit = Expect<Equal<
  Parse<'PUSH 10 IFZERO PUSH 42 ENDIF'>,
  [['PUSH', 10], ['IFZERO'], ['PUSH', 42], ['ENDIF']]
>>;

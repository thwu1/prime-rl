
import type { Expect, Equal } from 'type-testing';
import type { Instruction, Execute, Run } from '../src/stack-machine';
import type { Parse } from '../src/parser';

type RunProgram<S extends string> =
  Parse<S> extends infer P extends Instruction[]
    ? Run<P>
    : never;

// === Direct Execute tests with instruction tuples ===

// IFZERO pops top; if zero, execute true branch
type test_execute_ifzero_true = Expect<Equal<
  Execute<[0, 5], [['IFZERO'], ['PUSH', 1], ['ENDIF']]>,
  [1, 5]
>>;

// IFZERO pops top; if nonzero, skip to ENDIF
type test_execute_ifzero_false = Expect<Equal<
  Execute<[3, 5], [['IFZERO'], ['PUSH', 1], ['ENDIF']]>,
  [5]
>>;

// IFZERO with ELSE: true branch executes, else branch skipped
type test_execute_else_true = Expect<Equal<
  Execute<[0], [['IFZERO'], ['PUSH', 1], ['ELSE'], ['PUSH', 2], ['ENDIF']]>,
  [1]
>>;

// IFZERO with ELSE: false branch, else executes
type test_execute_else_false = Expect<Equal<
  Execute<[7], [['IFZERO'], ['PUSH', 1], ['ELSE'], ['PUSH', 2], ['ENDIF']]>,
  [2]
>>;

// Nested IFZERO during skip: inner IFZERO/ENDIF properly tracked
type test_execute_nested_skip = Expect<Equal<
  Execute<[1], [['IFZERO'], ['PUSH', 0], ['IFZERO'], ['PUSH', 99], ['ENDIF'], ['ENDIF']]>,
  []
>>;

// === String program tests ===

// Basic conditional true
type test_prog_ifzero_true = Expect<Equal<
  RunProgram<'PUSH 0 IFZERO PUSH 1 ENDIF'>,
  [1]
>>;

// Basic conditional false
type test_prog_ifzero_false = Expect<Equal<
  RunProgram<'PUSH 5 IFZERO PUSH 1 ENDIF'>,
  []
>>;

// Conditional with ELSE — true branch taken
type test_prog_else_true = Expect<Equal<
  RunProgram<'PUSH 0 IFZERO PUSH 1 ELSE PUSH 2 ENDIF'>,
  [1]
>>;

// Conditional with ELSE — false branch taken
type test_prog_else_false = Expect<Equal<
  RunProgram<'PUSH 3 IFZERO PUSH 1 ELSE PUSH 2 ENDIF'>,
  [2]
>>;

// Nested conditionals — both true
type test_prog_nested = Expect<Equal<
  RunProgram<'PUSH 0 IFZERO PUSH 0 IFZERO PUSH 42 ENDIF ENDIF'>,
  [42]
>>;

// Nested conditionals — outer false skips everything
type test_prog_nested_skip = Expect<Equal<
  RunProgram<'PUSH 1 IFZERO PUSH 0 IFZERO PUSH 99 ENDIF ENDIF'>,
  []
>>;

// Conditional with arithmetic: (3 - 3) = 0, true branch
type test_prog_cond_arith = Expect<Equal<
  RunProgram<'PUSH 3 PUSH 3 SUB IFZERO PUSH 10 ELSE PUSH 20 ENDIF'>,
  [10]
>>;

// Conditional with arithmetic: (5 - 3) = 2, false branch
type test_prog_cond_arith_false = Expect<Equal<
  RunProgram<'PUSH 5 PUSH 3 SUB IFZERO PUSH 10 ELSE PUSH 20 ENDIF'>,
  [20]
>>;

// Code continues normally after conditional
type test_prog_after_cond = Expect<Equal<
  RunProgram<'PUSH 0 IFZERO PUSH 3 ENDIF PUSH 4 ADD'>,
  [7]
>>;

// Nested with inner ELSE: outer true, inner false takes else
type test_prog_nested_else = Expect<Equal<
  RunProgram<'PUSH 0 IFZERO PUSH 1 IFZERO PUSH 8 ELSE PUSH 9 ENDIF ELSE PUSH 7 ENDIF'>,
  [9]
>>;

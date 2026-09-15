
import type { Expect, Equal } from 'type-testing';
import type { Instruction, Run } from '../src/stack-machine';
import type { Parse } from '../src/parser';

type RunProgram<S extends string> =
  Parse<S> extends infer P extends Instruction[]
    ? Run<P>
    : never;

// Basic arithmetic via string programs
type test_prog_add = Expect<Equal<RunProgram<'PUSH 3 PUSH 4 ADD'>, [7]>>;
type test_prog_sub = Expect<Equal<RunProgram<'PUSH 8 PUSH 3 SUB'>, [5]>>;
type test_prog_mul = Expect<Equal<RunProgram<'PUSH 6 PUSH 7 MUL'>, [42]>>;

// Multi-digit numbers
type test_prog_multidigit = Expect<Equal<RunProgram<'PUSH 10 PUSH 5 ADD'>, [15]>>;

// Complex: compute (3 + 4) * 2 = 14
type test_prog_complex = Expect<Equal<
  RunProgram<'PUSH 3 PUSH 4 ADD PUSH 2 MUL'>,
  [14]
>>;

// DUP and square
type test_prog_square = Expect<Equal<RunProgram<'PUSH 5 DUP MUL'>, [25]>>;

// SWAP then SUB
type test_prog_swap_sub = Expect<Equal<
  RunProgram<'PUSH 3 PUSH 7 SWAP SUB'>,
  [4]
>>;


import type { Expect, Equal } from 'type-testing';
import type { Step, Run } from '../src/stack-machine';

// PUSH
type test_push_empty = Expect<Equal<Step<[], ['PUSH', 5]>, [5]>>;
type test_push_existing = Expect<Equal<Step<[3], ['PUSH', 7]>, [7, 3]>>;

// ADD
type test_add_basic = Expect<Equal<Step<[3, 4], ['ADD']>, [7]>>;
type test_add_with_rest = Expect<Equal<Step<[1, 2, 10], ['ADD']>, [3, 10]>>;

// SUB (second - top)
type test_sub_basic = Expect<Equal<Step<[3, 7], ['SUB']>, [4]>>;
type test_sub_with_rest = Expect<Equal<Step<[2, 5, 10], ['SUB']>, [3, 10]>>;

// MUL
type test_mul_basic = Expect<Equal<Step<[3, 4], ['MUL']>, [12]>>;

// DUP
type test_dup = Expect<Equal<Step<[5, 3], ['DUP']>, [5, 5, 3]>>;

// SWAP
type test_swap = Expect<Equal<Step<[1, 2, 3], ['SWAP']>, [2, 1, 3]>>;
type test_swap_two = Expect<Equal<Step<[7, 3], ['SWAP']>, [3, 7]>>;

// POP
type test_pop = Expect<Equal<Step<[5, 3], ['POP']>, [3]>>;

// OVER (copy second to top)
type test_over = Expect<Equal<Step<[1, 2, 3], ['OVER']>, [2, 1, 2, 3]>>;
type test_over_two = Expect<Equal<Step<[4, 9], ['OVER']>, [9, 4, 9]>>;

// ROT (third to top)
type test_rot = Expect<Equal<Step<[1, 2, 3, 4], ['ROT']>, [3, 1, 2, 4]>>;
type test_rot_exact = Expect<Equal<Step<[1, 2, 3], ['ROT']>, [3, 1, 2]>>;

// Programs
type test_program_add = Expect<Equal<
  Run<[['PUSH', 3], ['PUSH', 4], ['ADD']]>,
  [7]
>>;

type test_program_sub = Expect<Equal<
  Run<[['PUSH', 5], ['PUSH', 3], ['SUB']]>,
  [2]
>>;

type test_program_square = Expect<Equal<
  Run<[['PUSH', 5], ['DUP'], ['MUL']]>,
  [25]
>>;

type test_program_swap_sub = Expect<Equal<
  Run<[['PUSH', 3], ['PUSH', 7], ['SWAP'], ['SUB']]>,
  [4]
>>;

type test_program_complex = Expect<Equal<
  Run<[['PUSH', 2], ['PUSH', 3], ['PUSH', 4], ['MUL'], ['ADD']]>,
  [14]
>>;

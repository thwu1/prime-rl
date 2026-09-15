
import type { Add, Subtract, Multiply } from './arithmetic';

export type Instruction =
  | ['PUSH', number]
  | ['ADD']
  | ['SUB']
  | ['MUL']
  | ['DUP']
  | ['SWAP']
  | ['POP']
  | ['OVER']
  | ['ROT']
  | ['IFZERO']
  | ['ELSE']
  | ['ENDIF'];

export type Step<Stack extends number[], Inst extends Instruction> =
  Inst extends ['PUSH', infer N extends number]
    ? [N, ...Stack]
  : Inst extends ['ADD']
    ? Stack extends [infer A extends number, infer B extends number, ...infer Rest extends number[]]
      ? [Add<A, B>, ...Rest]
      : never
  : Inst extends ['SUB']
    ? Stack extends [infer A extends number, infer B extends number, ...infer Rest extends number[]]
      ? [Subtract<A, B>, ...Rest]
      : never
  : Inst extends ['MUL']
    ? Stack extends [infer A extends number, infer B extends number, ...infer Rest extends number[]]
      ? [Multiply<A, B>, ...Rest]
      : never
  : Inst extends ['DUP']
    ? Stack extends [infer A extends number, ...infer Rest extends number[]]
      ? [A, A, ...Rest]
      : never
  : Inst extends ['POP']
    ? Stack extends [infer _A extends number, ...infer Rest extends number[]]
      ? Rest
      : never
  : Inst extends ['OVER']
    ? Stack extends [infer A extends number, infer B extends number, ...infer Rest extends number[]]
      ? [A, A, B, ...Rest]
      : never
  : Inst extends ['ROT']
    ? Stack extends [infer A extends number, infer B extends number, infer C extends number, ...infer Rest extends number[]]
      ? [B, C, A, ...Rest]
      : never
  : never;

export type Execute<Stack extends number[], Program extends Instruction[]> =
  Program extends [infer First extends Instruction, ...infer Remaining extends Instruction[]]
    ? Step<Stack, First> extends infer NewStack extends number[]
      ? Execute<NewStack, Remaining>
      : never
    : Stack;

export type Run<Program extends Instruction[]> = Execute<[], Program>;

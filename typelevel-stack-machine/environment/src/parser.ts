
import type { Instruction } from './stack-machine';

type Whitespace = ' ' | '\n' | '\t';

type TrimLeft<S extends string> =
  S extends `${Whitespace}${infer Rest}`
    ? TrimLeft<Rest>
    : S;

type Digit = '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9';

type ParseDigits<S extends string, Acc extends string = ''> =
  S extends `${infer D extends Digit}${infer Rest}`
    ? ParseDigits<Rest, `${Acc}${D}`>
    : [Acc, S];

type StringToNumber<S extends string> = S extends `${infer N extends number}` ? N : never;

type ParseInstruction<S extends string> =
  TrimLeft<S> extends `PUSH ${infer D extends Digit}${infer Rest}`
    ? [['PUSH', StringToNumber<D>], Rest]
  : TrimLeft<S> extends `ADD${infer Rest}` ? [['ADD'], Rest]
  : TrimLeft<S> extends `SUB${infer Rest}` ? [['SUB'], Rest]
  : TrimLeft<S> extends `MUL${infer Rest}` ? [['MUL'], Rest]
  : TrimLeft<S> extends `DUP${infer Rest}` ? [['DUP'], Rest]
  : TrimLeft<S> extends `SWAP${infer Rest}` ? [['SWAP'], Rest]
  : TrimLeft<S> extends `POP${infer Rest}` ? [['POP'], Rest]
  : TrimLeft<S> extends `OVER${infer Rest}` ? [['OVER'], Rest]
  : TrimLeft<S> extends `ROT${infer Rest}` ? [['ROT'], Rest]
  : TrimLeft<S> extends `IFZERO${infer Rest}` ? [['IFZERO'], Rest]
  : TrimLeft<S> extends `ENDIF${infer Rest}` ? [['ENDIF'], Rest]
  : TrimLeft<S> extends `ELSE${infer Rest}` ? [['ELSE'], Rest]
  : never;

type ParseProgram<S extends string, Acc extends Instruction[] = []> =
  TrimLeft<S> extends ''
    ? Acc
    : ParseInstruction<S> extends [infer Inst extends Instruction, infer Rest extends string]
      ? ParseProgram<Rest, [...Acc, Inst]>
      : never;

export type Parse<S extends string> = ParseProgram<S>;

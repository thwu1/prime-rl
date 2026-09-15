
import { DeepExclude } from '../src/types/DeepExclude';
import { DistributeMatchingUnions } from '../src/types/DistributeUnions';
import { BuildMany, SetDeep } from '../src/types/BuildMany';
import { IsMatching } from '../src/types/IsMatching';
import { Equal, Expect, Primitives } from '../src/types/helpers';
import { Option, State, BigUnion } from './utils';

// ============================================================
// IsMatching — Primitive matching
// ============================================================

type IM01 = Expect<Equal<IsMatching<string, unknown>, true>>;
type IM02 = Expect<Equal<IsMatching<number, string>, false>>;
type IM03 = Expect<Equal<IsMatching<'hello', string>, true>>;
type IM04 = Expect<Equal<IsMatching<string, 'hello'>, true>>;
type IM05 = Expect<Equal<IsMatching<boolean, true>, true>>;
type IM06 = Expect<Equal<IsMatching<42, unknown>, true>>;
type IM07 = Expect<Equal<IsMatching<null, undefined>, false>>;

// ============================================================
// IsMatching — Object matching
// ============================================================

type IM08 = Expect<Equal<IsMatching<{ a: string }, { a: number }>, false>>;
type IM09 = Expect<Equal<IsMatching<{ a: string }, { a: unknown }>, true>>;
type IM10 = Expect<Equal<IsMatching<{ a: string; b: number }, { a: string }>, true>>;
type IM11 = Expect<Equal<IsMatching<{ x: 1 }, {}>, true>>;

// ============================================================
// IsMatching — Tuple matching
// ============================================================

type IM12 = Expect<Equal<IsMatching<[1, 2], [number, number]>, true>>;
type IM13 = Expect<Equal<IsMatching<[1, 2], [1]>, false>>;
type IM14 = Expect<Equal<IsMatching<[string, number], [unknown, unknown]>, true>>;

// ============================================================
// IsMatching — Union matching
// ============================================================

type IM15 = Expect<Equal<IsMatching<string | number, string>, true>>;
type IM16 = Expect<Equal<IsMatching<{ a: 'x' | 'y' }, { a: 'x' }>, true>>;

// ============================================================
// IsMatching — Array matching
// ============================================================

type IM17 = Expect<Equal<IsMatching<number[], number[]>, true>>;
type IM18 = Expect<Equal<IsMatching<number[], string[]>, false>>;

// ============================================================
// SetDeep
// ============================================================

type SD01 = Expect<Equal<SetDeep<{ a: 1; b: 2 }, 3, ['a']>, { a: 3; b: 2 }>>;
type SD02 = Expect<Equal<
  SetDeep<{ a: { b: 1 } }, 2, ['a', 'b']>,
  { a: { b: 2 } }
>>;
type SD03 = Expect<Equal<SetDeep<[1, 2, 3], 'x', [1]>, [1, 'x', 3]>>;
type SD04 = Expect<Equal<SetDeep<{ a: 1 }, 2, []>, 2>>;
type SD05 = Expect<Equal<
  SetDeep<{ a: 1; b: { c: 2; d: 3 } }, 99, ['b', 'c']>,
  { a: 1; b: { c: 99; d: 3 } }
>>;

// ============================================================
// BuildMany
// ============================================================

type BM01 = Expect<Equal<
  BuildMany<{ a: 'x' | 'y' }, [['x', ['a']]] | [['y', ['a']]]>,
  { a: 'x' } | { a: 'y' }
>>;

// ============================================================
// DistributeMatchingUnions
// ============================================================

type DMU01 = Expect<Equal<
  DistributeMatchingUnions<'a' | 'b', 'a'>,
  'a' | 'b'
>>;
type DMU02 = Expect<Equal<
  DistributeMatchingUnions<{ a: 'x' | 'y' }, { a: 'x' }>,
  { a: 'x' } | { a: 'y' }
>>;
type DMU03 = Expect<Equal<
  DistributeMatchingUnions<['a' | 'b', 1 | 2], ['a', 1]>,
  ['a', 1] | ['a', 2] | ['b', 1] | ['b', 2]
>>;
type DMU04 = Expect<Equal<
  DistributeMatchingUnions<['a' | 'b', 1 | 2], ['a', unknown]>,
  ['a', 1 | 2] | ['b', 1 | 2]
>>;

// ============================================================
// DeepExclude — Primitives
// ============================================================

type DE_P01 = Expect<Equal<DeepExclude<string, string>, never>>;
type DE_P02 = Expect<Equal<DeepExclude<string | number, string>, number>>;
type DE_P03 = Expect<Equal<DeepExclude<string | number, boolean>, string | number>>;
type DE_P04 = Expect<Equal<DeepExclude<string, 'hello'>, string>>;
type DE_P05 = Expect<Equal<
  DeepExclude<Primitives, null | undefined>,
  string | number | bigint | boolean | symbol
>>;

// ============================================================
// DeepExclude — Literals
// ============================================================

type DE_L01 = Expect<Equal<DeepExclude<'hello' | 'bonjour', 'hello'>, 'bonjour'>>;
type DE_L02 = Expect<Equal<
  DeepExclude<'hello' | 'bonjour', 'hola'>,
  'hello' | 'bonjour'
>>;
type DE_L03 = Expect<Equal<DeepExclude<1 | 2 | 3, 3>, 1 | 2>>;
type DE_L04 = Expect<Equal<DeepExclude<'hello' | 1, string>, 1>>;
type DE_L05 = Expect<Equal<DeepExclude<'hello' | 1, number>, 'hello'>>;
type DE_L06 = Expect<Equal<DeepExclude<200n | number, bigint>, number>>;
type DE_L07 = Expect<Equal<DeepExclude<undefined | number, number>, undefined>>;

// ============================================================
// DeepExclude — Objects
// ============================================================

type DE_O01 = Expect<Equal<DeepExclude<{ a: 'x' | 'y' }, { a: string }>, never>>;
type DE_O02 = Expect<Equal<
  DeepExclude<{ a: 'x' | 'y' }, { a: 'x' }>,
  { a: 'y' }
>>;
type DE_O03 = Expect<Equal<
  DeepExclude<{ a: 'x' | 'y' }, { b: 'x' }>,
  { a: 'x' | 'y' }
>>;
type DE_O04 = Expect<Equal<
  DeepExclude<{ a: 'x' | 'y' }, { a: 'z' }>,
  { a: 'x' | 'y' }
>>;
type DE_O05 = Expect<Equal<
  DeepExclude<{ a: { b: 'x' | 'y' } }, { a: { b: 'x' } }>,
  { a: { b: 'y' } }
>>;
type DE_O06 = Expect<Equal<
  DeepExclude<{ a: { b: 'x' | 'y' | 'z' } }, { a: { b: 'x' } }>,
  { a: { b: 'y' } } | { a: { b: 'z' } }
>>;
type DE_O07 = Expect<Equal<
  DeepExclude<
    { a: { b: 'x' | 'y' | 'z' }; c: 'u' | 'v' },
    { a: { b: 'x' } }
  >,
  { a: { b: 'y' }; c: 'u' | 'v' } | { a: { b: 'z' }; c: 'u' | 'v' }
>>;
type DE_O08 = Expect<Equal<
  DeepExclude<
    { a: { b: 'x' | 'y' | 'z' }; c: 'u' | 'v' },
    { c: 'u' }
  >,
  { a: { b: 'x' | 'y' | 'z' }; c: 'v' }
>>;
type DE_O09 = Expect<Equal<
  DeepExclude<{ str: string | null | undefined }, { str: string }>,
  { str: null } | { str: undefined }
>>;
type DE_O10 = Expect<Equal<
  DeepExclude<{ str: string | null | undefined }, { str: null | undefined }>,
  { str: string }
>>;

// ============================================================
// DeepExclude — Tuples
// ============================================================

type DE_T01 = Expect<Equal<DeepExclude<['x' | 'y'], [string]>, never>>;
type DE_T02 = Expect<Equal<DeepExclude<['x' | 'y'], ['x']>, ['y']>>;
type DE_T03 = Expect<Equal<
  DeepExclude<[string, string], readonly [unknown, unknown]>,
  never
>>;
type DE_T04 = Expect<Equal<
  DeepExclude<[number, State], [unknown, { status: 'error' }]>,
  | [number, { status: 'idle' }]
  | [number, { status: 'loading' }]
  | [number, { status: 'success'; data: string }]
>>;
type DE_T05 = Expect<Equal<DeepExclude<[['x' | 'y']], [['x']]>, [['y']]>>;
type DE_T06 = Expect<Equal<
  DeepExclude<[['x' | 'y' | 'z']], [['x']]>,
  [['y']] | [['z']]
>>;
type DE_T07 = Expect<Equal<DeepExclude<['x' | 'y'], ['z']>, ['x' | 'y']>>;
type DE_T08 = Expect<Equal<DeepExclude<['x' | 'y'], []>, ['x' | 'y']>>;
type DE_T09 = Expect<Equal<DeepExclude<[[number]], [[unknown]]>, never>>;
type DE_T10 = Expect<Equal<DeepExclude<[[[number]]], [[[unknown]]]>, never>>;
type DE_T11 = Expect<Equal<DeepExclude<[[[[number]]]], [[[[unknown]]]]>, never>>;

// ============================================================
// DeepExclude — Variadic arrays
// ============================================================

type DE_V01 = Expect<Equal<DeepExclude<number[], [number, ...number[]]>, []>>;
type DE_V02 = Expect<Equal<DeepExclude<number[], []>, [number, ...number[]]>>;
type DE_V03 = Expect<Equal<DeepExclude<number[], [...number[], number]>, []>>;

// ============================================================
// DeepExclude — Lists (non-tuple arrays)
// ============================================================

type DE_LS01 = Expect<Equal<DeepExclude<(1 | 2 | 3)[], (1 | 2 | 3)[]>, never>>;
type DE_LS02 = Expect<Equal<DeepExclude<(1 | 2 | 3)[], unknown[]>, never>>;
type DE_LS03 = Expect<Equal<
  DeepExclude<(1 | 2 | 3)[] | string[], string[]>,
  (1 | 2 | 3)[]
>>;
type DE_LS04 = Expect<Equal<DeepExclude<(1 | 2 | 3)[], 1[]>, (1 | 2 | 3)[]>>;

// ============================================================
// DeepExclude — Sets
// ============================================================

type DE_S01 = Expect<Equal<DeepExclude<Set<1 | 2 | 3>, Set<1 | 2 | 3>>, never>>;
type DE_S02 = Expect<Equal<DeepExclude<Set<1 | 2 | 3>, Set<unknown>>, never>>;
type DE_S03 = Expect<Equal<
  DeepExclude<Set<1 | 2 | 3> | Set<string>, Set<string>>,
  Set<1 | 2 | 3>
>>;

// ============================================================
// DeepExclude — Maps
// ============================================================

type DE_M01 = Expect<Equal<
  DeepExclude<Map<string, 1 | 2 | 3>, Map<string, 1 | 2 | 3>>,
  never
>>;
type DE_M02 = Expect<Equal<
  DeepExclude<Map<string, 1 | 2 | 3>, Map<string, unknown>>,
  never
>>;
type DE_M03 = Expect<Equal<
  DeepExclude<Map<string, 1 | 2 | 3> | Map<string, string>, Map<string, string>>,
  Map<string, 1 | 2 | 3>
>>;

// ============================================================
// DeepExclude — Complex / real-world patterns
// ============================================================

type Colors = 'pink' | 'purple' | 'red' | 'yellow' | 'blue';

type DE_C01 = Expect<Equal<DeepExclude<'a' | 'b' | 'c', 'a'>, 'b' | 'c'>>;

type DE_C02 = Expect<Equal<
  DeepExclude<
    | { type: 'textWithColor'; color: Colors }
    | { type: 'textWithColorAndBg'; color: Colors; bgColor: Colors },
    { type: 'textWithColor' }
  >,
  { type: 'textWithColorAndBg'; color: Colors; bgColor: Colors }
>>;

type DE_C03 = Expect<Equal<
  DeepExclude<
    [Option<{ type: 'a' } | { type: 'b' }>, 'c' | 'd'],
    [{ kind: 'some'; value: { type: 'a' } }, any]
  >,
  | [{ kind: 'none' }, 'c' | 'd']
  | [{ kind: 'some'; value: { type: 'b' } }, 'c' | 'd']
>>;

type DE_C04 = Expect<Equal<
  DeepExclude<
    { x: 'a' | 'b'; y: 'c' | 'd'; z: 'e' | 'f' },
    { x: 'a'; y: 'c' }
  >,
  | { x: 'b'; y: 'c'; z: 'e' | 'f' }
  | { x: 'b'; y: 'd'; z: 'e' | 'f' }
  | { x: 'a'; y: 'd'; z: 'e' | 'f' }
>>;

// ============================================================
// DeepExclude — Multiple patterns (union of patterns)
// ============================================================

type DE_MP01 = Expect<Equal<
  DeepExclude<
    { x: 'a' | 'b'; y: 'c' | 'd'; z: 'e' | 'f' },
    { x: 'a'; y: 'c' } | { x: 'b'; y: 'c' }
  >,
  | { x: 'b'; y: 'd'; z: 'e' | 'f' }
  | { x: 'a'; y: 'd'; z: 'e' | 'f' }
>>;

type DE_MP02 = Expect<Equal<
  DeepExclude<
    { a: { b: 'x' | 'y' | 'z' }; c: 'u' | 'v' },
    { c: 'u' } | { a: { b: 'x' } }
  >,
  { a: { b: 'y' }; c: 'v' } | { a: { b: 'z' }; c: 'v' }
>>;

// ============================================================
// DeepExclude — readonly tuples
// ============================================================

type DE_RO01 = Expect<Equal<
  DeepExclude<readonly ['a' | 'b', 'c' | 'd'], ['a', 'c']>,
  ['a', 'd'] | ['b', 'c'] | ['b', 'd']
>>;

type DE_RO02 = Expect<Equal<
  DeepExclude<
    readonly ['a' | 'b', 'c' | 'd'],
    ['a', 'c'] | ['a', 'd'] | ['b', 'c'] | ['b', 'd']
  >,
  never
>>;

// ============================================================
// DeepExclude — Optional properties
// ============================================================

type InputWithOptional = {
  type: 'a';
  data?: { type: 'img'; src: string } | { type: 'text'; p: string };
};
type PatternWithOptional = {
  readonly type: 'a';
  readonly data?: { readonly type: 'img' };
};

type DE_OP01 = Expect<Equal<
  DeepExclude<InputWithOptional, PatternWithOptional>,
  { type: 'a'; data: { type: 'text'; p: string } }
>>;

// ============================================================
// DeepExclude — unknown in pattern
// ============================================================

type DE_U01 = Expect<Equal<
  DeepExclude<
    [number, { type: 'a'; b: string }],
    [unknown, { type: 'a'; b: unknown }]
  >,
  never
>>;

// ============================================================
// DeepExclude — union in pattern b
// ============================================================

type DE_UP01 = Expect<Equal<
  DeepExclude<
    {
      type: 'c';
      value:
        | { type: 'd'; value: boolean }
        | { type: 'e'; value: string[] }
        | { type: 'f'; value: number[] };
    },
    {
      type: 'c';
      value: { type: 'd' | 'e' };
    }
  >,
  { type: 'c'; value: { type: 'f'; value: number[] } }
>>;

// ============================================================
// DeepExclude — Big unions
// ============================================================

type DE_BU01 = Expect<Equal<
  DeepExclude<
    | { type: 'textWithColor'; union: BigUnion }
    | { type: 'textWithColorAndBg'; union: BigUnion; union2: BigUnion },
    { type: 'textWithColor' }
  >,
  { type: 'textWithColorAndBg'; union: BigUnion; union2: BigUnion }
>>;

// ============================================================
// DeepExclude — Nested union exclusion
// ============================================================

type DE_NU01 = Expect<Equal<
  DeepExclude<
    ['a' | 'b' | 'c', 'a' | 'b' | 'c'],
    ['b' | 'c', 'b' | 'c']
  >,
  ['a', 'a'] | ['a', 'b'] | ['a', 'c'] | ['b', 'a'] | ['c', 'a']
>>;

// ============================================================
// DeepExclude — Empty list patterns
// ============================================================

type DE_EL01 = Expect<Equal<
  DeepExclude<{ values: (1 | 2 | 3)[] }, { values: [] }>,
  { values: [1 | 2 | 3, ...(1 | 2 | 3)[]] }
>>;

type DE_EL02 = Expect<Equal<
  DeepExclude<[] | [1, 2, 3], []>,
  [1, 2, 3]
>>;

// ============================================================
// Negative assertions — anti-cheat
// ============================================================

// DeepExclude is NOT just Exclude (deep distribution matters)
// @ts-expect-error
type NEG01 = Expect<Equal<DeepExclude<{ a: 'x' | 'y' }, { a: 'x' }>, never>>;

// IsMatching is NOT always true
// @ts-expect-error
type NEG02 = Expect<Equal<IsMatching<number, string>, true>>;

// DeepExclude does NOT return the input unchanged
// @ts-expect-error
type NEG03 = Expect<Equal<DeepExclude<string | number, string>, string | number>>;

// IsMatching is NOT always false
// @ts-expect-error
type NEG04 = Expect<Equal<IsMatching<string, unknown>, false>>;

// DistributeMatchingUnions actually distributes unions
// @ts-expect-error
type NEG05 = Expect<Equal<
  DistributeMatchingUnions<{ a: 'x' | 'y' }, { a: 'x' }>,
  { a: 'x' | 'y' }
>>;

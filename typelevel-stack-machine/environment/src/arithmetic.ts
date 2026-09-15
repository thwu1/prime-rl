
// Type-level natural number arithmetic using tuple length encoding

export type BuildTuple<N extends number, T extends unknown[] = []> =
  T['length'] extends N ? T : BuildTuple<N, [...T, unknown]>;

export type Add<A extends number, B extends number> =
  [...BuildTuple<A>, ...BuildTuple<B>]['length'] & number;

export type Subtract<A extends number, B extends number> =
  BuildTuple<A> extends [...BuildTuple<B>, ...infer Rest]
    ? Rest['length'] & number
    : 0;

export type Multiply<A extends number, B extends number, Acc extends number = 0> =
  B extends 0
    ? Acc
    : Multiply<A, Subtract<B, 1>, Add<Acc, B>>;

export type IsZero<N extends number> = N extends 0 ? true : false;

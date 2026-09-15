import { BuildMany } from './BuildMany';
import type {
  IsAny,
  Values,
  Flatten,
  IsUnion,
  IsPlainObject,
  Length,
  UnionToTuple,
  IsReadonlyArray,
  ValueOf,
  MaybeAddReadonly,
  IsStrictArray,
} from './helpers';
import { IsMatching } from './IsMatching';

// TODO: Implement DistributeMatchingUnions, FindUnionsMany, FindUnions, and Distribute
export type DistributeMatchingUnions<a, p> = a;

export type FindUnionsMany<a, p, path extends PropertyKey[] = []> = [];

export type FindUnions<a, p, path extends PropertyKey[] = []> = [];

export type Distribute<unions extends readonly any[]> = [];

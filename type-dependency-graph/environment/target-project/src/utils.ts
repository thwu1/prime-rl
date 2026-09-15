import { Identifiable } from "./core";

export type DeepReadonly<T> = {
  readonly [K in keyof T]: T[K] extends object ? DeepReadonly<T[K]> : T[K];
};

export type Nullable<T> = { [K in keyof T]: T[K] | null };

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type ExtractId<T> = T extends Identifiable ? T["id"] : never;

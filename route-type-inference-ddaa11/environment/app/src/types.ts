
// ============ Utility types (correct) ============

export type Expect<T extends true> = T

export type Equal<X, Y> =
  (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? true : false

export type UnionToIntersection<U> =
  (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never

// ============ Path parameter types ============

// Extracts a single parameter key from a route path component.
// ':id' → 'id', ':id{[0-9]+}' → 'id', ':name{\\w+}?' → 'name?', 'users' → never
type ParamKey<Component> = Component extends `:${infer NameWithPattern}`
  ? NameWithPattern extends `${infer Name}{${infer _Rest}`
    ? Name
    : NameWithPattern
  : never

// Extracts all parameter keys from a route path string.
// '/users/:id/posts/:postId' → 'id' | 'postId'
export type ParamKeys<Path> = Path extends `${infer Component}/${infer Rest}`
  ? ParamKey<Component>
  : ParamKey<Path>

// Converts a parameter key to a typed record.
// 'id' → { id: string }, 'name?' → Record<'name', string | undefined>
export type ParamKeyToRecord<T extends string> = { [K in T]: string }

// Merges two path strings, normalizing slashes at the join point.
export type MergePath<A extends string, B extends string> = B extends ''
  ? MergePath<A, '/'>
  : A extends ''
    ? B
    : A extends `${infer P}/`
      ? B extends `/${infer Q}`
        ? `${P}/${Q}`
        : `${P}/${B}`
      : B extends `/${infer Q}`
        ? `${A}/${Q}`
        : `${A}/${B}`

// Adds extracted path parameters to an input type.
export type AddParam<I, P extends string> =
  I extends { param: infer _ }
    ? I
    : I & { param: UnionToIntersection<ParamKeyToRecord<ParamKeys<P>>> }

// Extracts all path parameters as a single flattened record type.
export type ExtractAllParams<Path extends string> =
  UnionToIntersection<ParamKeyToRecord<ParamKeys<Path>>>

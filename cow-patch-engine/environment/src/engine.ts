
import { DraftState, DRAFT_STATE, Patch, Recipe } from "./types";

/**
 * produce(base, recipe) → new state
 *
 * Creates a mutable draft of `base`, passes it to `recipe` for mutation,
 * then produces a new immutable state tree with structural sharing.
 *
 * Contract:
 * - If recipe makes no changes, return base (same reference).
 * - Unmodified subtrees share identity (===) with the original.
 * - Base state is never mutated.
 * - Result is recursively frozen (Object.freeze).
 * - Supports nested plain objects and arrays.
 * - If recipe returns a non-undefined, non-draft value, use it as replacement.
 */
export function produce<T extends object>(base: T, recipe: Recipe<T>): T {
  // TODO: implement
  throw new Error("produce: not implemented");
}

/**
 * produceWithPatches(base, recipe) → [result, patches, inversePatches]
 *
 * Same as produce, but also generates RFC-6902-style patches describing
 * the changes, plus inverse patches that can undo them.
 *
 * Patch format: { op: "add"|"replace"|"remove", path: [...], value? }
 * - Object keys in paths are strings; array indices are numbers.
 * - applyPatches(base, patches) must deeply equal result.
 * - applyPatches(result, inversePatches) must deeply equal base.
 * - Patch values that reference draft internals must be deep-cloned.
 */
export function produceWithPatches<T extends object>(
  base: T,
  recipe: Recipe<T>
): [T, Patch[], Patch[]] {
  // TODO: implement
  throw new Error("produceWithPatches: not implemented");
}

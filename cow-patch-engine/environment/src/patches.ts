
import { Patch } from "./types";

/**
 * applyPatches(base, patches) → new state
 *
 * Applies an array of RFC-6902-style patches to produce a new state.
 *
 * Contract:
 * - Supports objects, arrays, Maps, and Sets as targets.
 * - "add": insert value at path. For arrays, splice at index; "-" appends.
 *          For Sets, add value. For Maps, set(key, value).
 * - "replace": overwrite value at path. For Maps, use set(). Not valid for Sets.
 * - "remove": delete at path. For arrays, splice out element.
 *             For Maps, delete(key). For Sets, delete(patch.value).
 * - Deep-clone patch values before insertion to prevent external mutation.
 * - Block prototype pollution: throw on paths containing "__proto__",
 *   "constructor", or "prototype".
 * - Throw on unresolvable paths.
 * - Return a copy of base with patches applied (do not mutate base).
 */
export function applyPatches<T>(base: T, patches: readonly Patch[]): T {
  // TODO: implement
  throw new Error("applyPatches: not implemented");
}

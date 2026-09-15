#!/usr/bin/env python3
"""
Fix all bugs in /app/src/patch-engine.ts by writing the corrected implementation.

Bugs fixed:
1. escapeJsonPointerSegment: escape ~ before / (was reversed)
2. unescapeJsonPointerSegment: unescape ~1 before ~0 (was reversed)
3. isPathPrefix: use !== instead of != for strict type comparison
4. fromRFC6902: "/" maps to [""] not [] (only "" is root)
5. compressPatches: prune descendant patches when parent remove is added
6. detectConflicts: detect ancestor/descendant path conflicts
7. rebasePatches: adjust array indices for add/remove in over patches
8. applyPatches: use splice for array add (insert, not overwrite)
9. applyPatches: use splice for array remove (shift, not delete)
10. invertPatches: retrieve old values from pre-state via path traversal
11. invertPatches: forward-simulate intermediate state using applyPatches
12. invertPatches: reverse the output array order
"""


CORRECTED = r'''import {
  ImmerPatch,
  RFC6902Patch,
  PatchConflict,
  PathSegment,
} from "./types.js";

// ============================================
// Deep Clone Utility
// ============================================

function cloneDeep<T>(value: T): T {
  if (value === undefined || value === null) return value;
  if (typeof value !== "object") return value;
  return JSON.parse(JSON.stringify(value));
}

// ============================================
// State Traversal
// ============================================

function getAtPath(state: any, path: PathSegment[]): any {
  let current = state;
  for (const seg of path) {
    if (current == null) return undefined;
    current = current[seg];
  }
  return current;
}

// ============================================
// Path Utilities
// ============================================

export function pathsEqual(a: PathSegment[], b: PathSegment[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((seg, i) => seg === b[i]);
}

export function isPathPrefix(
  prefix: PathSegment[],
  path: PathSegment[]
): boolean {
  if (prefix.length > path.length) return false;
  for (let i = 0; i < prefix.length; i++) {
    if (prefix[i] !== path[i]) return false;
  }
  return true;
}

export function isPathPrefixStrict(
  prefix: PathSegment[],
  path: PathSegment[]
): boolean {
  return prefix.length < path.length && isPathPrefix(prefix, path);
}

// ============================================
// RFC-6902 JSON Patch Conversion
// ============================================

function escapeJsonPointerSegment(segment: PathSegment): string {
  const s = String(segment);
  return s.replaceAll("~", "~0").replaceAll("/", "~1");
}

function unescapeJsonPointerSegment(raw: string): PathSegment {
  const s = raw.replaceAll("~1", "/").replaceAll("~0", "~");
  const num = Number(s);
  if (Number.isInteger(num) && num >= 0 && String(num) === s) {
    return num;
  }
  return s;
}

export function toRFC6902(patches: ImmerPatch[]): RFC6902Patch[] {
  return patches.map((patch) => {
    const pathStr =
      patch.path.length === 0
        ? ""
        : "/" + patch.path.map(escapeJsonPointerSegment).join("/");
    const result: RFC6902Patch = { op: patch.op, path: pathStr };
    if ("value" in patch && patch.value !== undefined) {
      result.value = cloneDeep(patch.value);
    }
    return result;
  });
}

export function fromRFC6902(patches: RFC6902Patch[]): ImmerPatch[] {
  return patches.map((patch) => {
    let path: PathSegment[];
    if (patch.path === "") {
      path = [];
    } else {
      const raw = patch.path.startsWith("/")
        ? patch.path.substring(1)
        : patch.path;
      path = raw.split("/").map(unescapeJsonPointerSegment);
    }

    const result: ImmerPatch = {
      op: patch.op as ImmerPatch["op"],
      path,
    };
    if ("value" in patch && patch.value !== undefined) {
      result.value = cloneDeep(patch.value);
    }
    return result;
  });
}

// ============================================
// Patch Compression
// ============================================

export function compressPatches(patches: ImmerPatch[]): ImmerPatch[] {
  const result: ImmerPatch[] = [];

  for (const patch of patches) {
    let merged = false;

    for (let i = result.length - 1; i >= 0; i--) {
      const existing = result[i];

      if (pathsEqual(existing.path, patch.path)) {
        if (existing.op === "replace" && patch.op === "replace") {
          existing.value = cloneDeep(patch.value);
          merged = true;
          break;
        }
        if (existing.op === "add" && patch.op === "replace") {
          existing.value = cloneDeep(patch.value);
          merged = true;
          break;
        }
        if (existing.op === "add" && patch.op === "remove") {
          result.splice(i, 1);
          merged = true;
          break;
        }
        if (existing.op === "replace" && patch.op === "remove") {
          existing.op = "remove";
          delete existing.value;
          merged = true;
          break;
        }
        if (existing.op === "remove" && patch.op === "add") {
          existing.op = "replace";
          existing.value = cloneDeep(patch.value);
          merged = true;
          break;
        }
        break;
      }

      if (
        existing.op === "remove" &&
        isPathPrefixStrict(existing.path, patch.path)
      ) {
        merged = true;
        break;
      }
    }

    if (!merged) {
      if (patch.op === "remove") {
        for (let i = result.length - 1; i >= 0; i--) {
          if (isPathPrefixStrict(patch.path, result[i].path)) {
            result.splice(i, 1);
          }
        }
      }
      result.push(cloneDeep(patch));
    }
  }

  return result;
}

// ============================================
// Conflict Detection
// ============================================

export function detectConflicts(
  branchA: ImmerPatch[],
  branchB: ImmerPatch[]
): PatchConflict[] {
  const conflicts: PatchConflict[] = [];

  for (let a = 0; a < branchA.length; a++) {
    for (let b = 0; b < branchB.length; b++) {
      const pA = branchA[a];
      const pB = branchB[b];

      if (pathsEqual(pA.path, pB.path)) {
        if (pA.op === "remove" && pB.op === "remove") {
          continue;
        }
        if (pA.op === "remove") {
          conflicts.push({
            type: "delete-write",
            pathA: [...pA.path],
            pathB: [...pB.path],
            patchIndexA: a,
            patchIndexB: b,
          });
        } else if (pB.op === "remove") {
          conflicts.push({
            type: "write-delete",
            pathA: [...pA.path],
            pathB: [...pB.path],
            patchIndexA: a,
            patchIndexB: b,
          });
        } else {
          conflicts.push({
            type: "write-write",
            pathA: [...pA.path],
            pathB: [...pB.path],
            patchIndexA: a,
            patchIndexB: b,
          });
        }
      }

      if (isPathPrefixStrict(pA.path, pB.path) && pA.op === "remove") {
        conflicts.push({
          type: "delete-write",
          pathA: [...pA.path],
          pathB: [...pB.path],
          patchIndexA: a,
          patchIndexB: b,
        });
      }
      if (isPathPrefixStrict(pB.path, pA.path) && pB.op === "remove") {
        conflicts.push({
          type: "write-delete",
          pathA: [...pA.path],
          pathB: [...pB.path],
          patchIndexA: a,
          patchIndexB: b,
        });
      }
    }
  }

  return conflicts;
}

// ============================================
// Operational Transformation (Rebase)
// ============================================

export function rebasePatches(
  patches: ImmerPatch[],
  over: ImmerPatch[]
): ImmerPatch[] {
  const result: ImmerPatch[] = [];

  for (const patch of patches) {
    let transformed: ImmerPatch = cloneDeep(patch);
    let drop = false;

    for (const op of over) {
      if (drop) break;

      if (pathsEqual(op.path, transformed.path)) {
        if (op.op === "remove") {
          drop = true;
        }
        continue;
      }

      if (
        op.op === "remove" &&
        isPathPrefixStrict(op.path, transformed.path)
      ) {
        drop = true;
        break;
      }

      if (op.path.length >= 1 && transformed.path.length >= 1) {
        const opParent = op.path.slice(0, -1);
        const transformedParent = transformed.path.slice(0, -1);
        const opIndex = op.path[op.path.length - 1];
        const transformedIndex =
          transformed.path[transformed.path.length - 1];

        if (
          typeof opIndex === "number" &&
          typeof transformedIndex === "number" &&
          pathsEqual(opParent, transformedParent)
        ) {
          if (op.op === "add" && transformedIndex >= opIndex) {
            transformed = {
              ...transformed,
              path: [
                ...transformed.path.slice(0, -1),
                transformedIndex + 1,
              ],
            };
          } else if (op.op === "remove" && transformedIndex > opIndex) {
            transformed = {
              ...transformed,
              path: [
                ...transformed.path.slice(0, -1),
                transformedIndex - 1,
              ],
            };
          }
        }
      }
    }

    if (!drop) {
      result.push(transformed);
    }
  }

  return result;
}

// ============================================
// Patch Application
// ============================================

export function applyPatches(state: any, patches: ImmerPatch[]): any {
  let result = cloneDeep(state);

  for (const patch of patches) {
    if (patch.path.length === 0) {
      if (patch.op === "replace" || patch.op === "add") {
        result = cloneDeep(patch.value);
      } else if (patch.op === "remove") {
        result = undefined;
      }
      continue;
    }

    let parent = result;
    for (let i = 0; i < patch.path.length - 1; i++) {
      parent = parent[patch.path[i]];
    }

    const key = patch.path[patch.path.length - 1];

    if (patch.op === "add") {
      if (Array.isArray(parent) && typeof key === "number") {
        parent.splice(key, 0, cloneDeep(patch.value));
      } else {
        parent[key] = cloneDeep(patch.value);
      }
    } else if (patch.op === "replace") {
      parent[key] = cloneDeep(patch.value);
    } else if (patch.op === "remove") {
      if (Array.isArray(parent) && typeof key === "number") {
        parent.splice(key, 1);
      } else {
        delete parent[key];
      }
    }
  }

  return result;
}

// ============================================
// Inverse Patch Generation
// ============================================

export function invertPatches(
  patches: ImmerPatch[],
  preState: any
): ImmerPatch[] {
  const inverse: ImmerPatch[] = [];
  let currentState = cloneDeep(preState);

  for (const patch of patches) {
    if (patch.op === "replace") {
      const oldValue = getAtPath(currentState, patch.path);
      inverse.push({
        op: "replace",
        path: [...patch.path],
        value: cloneDeep(oldValue),
      });
    } else if (patch.op === "add") {
      inverse.push({
        op: "remove",
        path: [...patch.path],
      });
    } else if (patch.op === "remove") {
      const oldValue = getAtPath(currentState, patch.path);
      inverse.push({
        op: "add",
        path: [...patch.path],
        value: cloneDeep(oldValue),
      });
    }

    currentState = applyPatches(currentState, [patch]);
  }

  return inverse.reverse();
}
'''

with open("/app/src/patch-engine.ts", "w") as f:
    f.write(CORRECTED.lstrip("\n"))

print("All 12 bugs fixed in /app/src/patch-engine.ts")

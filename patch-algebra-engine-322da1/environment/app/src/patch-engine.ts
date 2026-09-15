import {
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
    if (prefix[i] != path[i]) return false;
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
  return s.replaceAll("/", "~1").replaceAll("~", "~0");
}

function unescapeJsonPointerSegment(raw: string): PathSegment {
  const s = raw.replaceAll("~0", "~").replaceAll("~1", "/");
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
    if (patch.path === "" || patch.path === "/") {
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
      parent[key] = cloneDeep(patch.value);
    } else if (patch.op === "replace") {
      parent[key] = cloneDeep(patch.value);
    } else if (patch.op === "remove") {
      delete parent[key];
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

  for (const patch of patches) {
    if (patch.op === "replace") {
      inverse.push({
        op: "replace",
        path: [...patch.path],
        value: undefined,
      });
    } else if (patch.op === "add") {
      inverse.push({
        op: "remove",
        path: [...patch.path],
      });
    } else if (patch.op === "remove") {
      inverse.push({
        op: "add",
        path: [...patch.path],
        value: undefined,
      });
    }
  }

  return inverse;
}

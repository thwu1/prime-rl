
import { Patch } from "./types";

function deepCloneValue(obj: any): any {
  if (obj === null || typeof obj !== "object") return obj;
  if (Array.isArray(obj)) return obj.map(deepCloneValue);
  if (obj instanceof Map)
    return new Map(
      Array.from(obj.entries()).map(([k, v]) => [k, deepCloneValue(v)])
    );
  if (obj instanceof Set)
    return new Set(Array.from(obj).map(deepCloneValue));
  const result: any = Object.create(Object.getPrototypeOf(obj));
  for (const key of Object.keys(obj))
    result[key] = deepCloneValue((obj as any)[key]);
  return result;
}

function shallowClone(obj: any): any {
  if (Array.isArray(obj)) return obj.slice();
  if (obj instanceof Map) return new Map(obj);
  if (obj instanceof Set) return new Set(obj);
  return { ...obj };
}

function checkProtoPollution(segment: string | number): void {
  if (
    typeof segment === "string" &&
    (segment === "__proto__" ||
      segment === "constructor" ||
      segment === "prototype")
  ) {
    throw new Error(
      `Patching reserved attribute "${segment}" is not allowed`
    );
  }
}

function getChild(target: any, key: string | number): any {
  if (target instanceof Map) return target.get(key);
  return target[key];
}

function setChild(target: any, key: string | number, value: any): void {
  if (target instanceof Map) {
    target.set(key, value);
    return;
  }
  target[key] = value;
}

export function applyPatches<T>(base: T, patches: readonly Patch[]): T {
  if (patches.length === 0) return shallowClone(base);

  let root: any = shallowClone(base);

  for (const patch of patches) {
    const { op, path } = patch;

    // Handle root replacement
    if (path.length === 0) {
      if (op === "replace") {
        root = deepCloneValue(patch.value);
      }
      continue;
    }

    // Navigate to parent, cloning along the way to avoid mutating shared refs
    let target: any = root;
    for (let i = 0; i < path.length - 1; i++) {
      const segment = path[i];
      checkProtoPollution(segment);

      let child = getChild(target, segment);
      if (child === null || child === undefined || typeof child !== "object") {
        throw new Error(
          "Cannot apply patch, path doesn't resolve: " + path.join("/")
        );
      }

      const cloned = shallowClone(child);
      setChild(target, segment, cloned);
      target = cloned;
    }

    const key = path[path.length - 1];
    checkProtoPollution(key);

    const clonedValue = deepCloneValue(patch.value);

    if (target instanceof Set) {
      switch (op) {
        case "add":
          target.add(clonedValue);
          break;
        case "remove":
          target.delete(patch.value);
          break;
        default:
          throw new Error(`Sets cannot have "${op}" patches`);
      }
    } else if (target instanceof Map) {
      switch (op) {
        case "add":
        case "replace":
          target.set(key, clonedValue);
          break;
        case "remove":
          target.delete(key);
          break;
        default:
          throw new Error("Unsupported patch operation: " + op);
      }
    } else if (Array.isArray(target)) {
      switch (op) {
        case "add":
          if (key === "-") target.push(clonedValue);
          else target.splice(key as number, 0, clonedValue);
          break;
        case "replace":
          target[key as number] = clonedValue;
          break;
        case "remove":
          target.splice(key as number, 1);
          break;
        default:
          throw new Error("Unsupported patch operation: " + op);
      }
    } else {
      switch (op) {
        case "add":
        case "replace":
          target[key as any] = clonedValue;
          break;
        case "remove":
          delete target[key as any];
          break;
        default:
          throw new Error("Unsupported patch operation: " + op);
      }
    }
  }

  return root;
}

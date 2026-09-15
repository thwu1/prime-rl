
import { DraftState, DRAFT_STATE, Patch, Recipe } from "./types";

function isDraftable(value: any): boolean {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return true;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function shallowCopy(base: any): any {
  if (Array.isArray(base)) return base.slice();
  return { ...base };
}

function latest(state: DraftState): any {
  return state.copy ?? state.base;
}

function prepareCopy(state: DraftState): void {
  if (!state.copy) {
    state.copy = shallowCopy(state.base);
  }
}

function markChanged(state: DraftState): void {
  if (!state.modified) {
    state.modified = true;
    prepareCopy(state);
    if (state.parent) {
      markChanged(state.parent);
    }
  }
}

function deepFreeze(obj: any): void {
  if (obj === null || typeof obj !== "object" || Object.isFrozen(obj)) return;
  Object.freeze(obj);
  if (Array.isArray(obj)) {
    for (const item of obj) deepFreeze(item);
  } else if (obj instanceof Map || obj instanceof Set) {
    // skip
  } else {
    for (const key of Object.keys(obj)) deepFreeze((obj as any)[key]);
  }
}

function cloneValue(value: any): any {
  if (value === null || typeof value !== "object") return value;
  const ds: DraftState | undefined = value[DRAFT_STATE];
  if (ds) return cloneValue(ds.modified ? ds.copy : ds.base);
  if (Array.isArray(value)) return value.map(cloneValue);
  if (value instanceof Map)
    return new Map(
      Array.from(value.entries()).map(([k, v]) => [k, cloneValue(v)])
    );
  if (value instanceof Set)
    return new Set(Array.from(value).map(cloneValue));
  const result: any = {};
  for (const key of Object.keys(value)) result[key] = cloneValue(value[key]);
  return result;
}

function createDraft(
  base: any,
  parent: DraftState | null,
  parentKey: string | number | null
): any {
  const isArr = Array.isArray(base);
  const state: DraftState = {
    type: isArr ? "array" : "object",
    base,
    copy: null,
    modified: false,
    finalized: false,
    parent,
    parentKey,
    assigned: new Map(),
    draft: null as any,
    revoke: null,
  };

  const target: any = isArr ? [] : {};

  const handler: ProxyHandler<any> = {
    get(_t: any, prop: PropertyKey) {
      if (prop === DRAFT_STATE) return state;
      if (typeof prop === "symbol") return latest(state)[prop];

      const source = latest(state);
      if (!Object.prototype.hasOwnProperty.call(source, prop)) {
        return source[prop];
      }

      const value = source[prop];
      if (state.finalized || !isDraftable(value)) return value;

      if (value === state.base[prop]) {
        prepareCopy(state);
        const child = createDraft(
          value,
          state,
          isArr ? Number(prop as string) : (prop as string)
        );
        state.copy[prop] = child;
        return child;
      }
      return value;
    },

    set(_t: any, prop: PropertyKey, value: any) {
      if (typeof prop === "symbol") return true;

      if (isArr && prop === "length") {
        prepareCopy(state);
        if (!state.modified) markChanged(state);
        state.copy.length = value;
        return true;
      }

      const source = latest(state);
      const current = source[prop];
      const assignKey: string | number = isArr
        ? Number(prop as string)
        : (prop as string);

      const childDs: DraftState | undefined = value?.[DRAFT_STATE];
      if (childDs && childDs.base === state.base[prop]) {
        prepareCopy(state);
        state.copy[prop] = state.base[prop];
        state.assigned.set(assignKey, false);
        return true;
      }

      if (!state.modified) {
        if (
          Object.is(value, current) &&
          (value !== undefined || (prop as string) in state.base)
        ) {
          return true;
        }
        prepareCopy(state);
        markChanged(state);
      }

      state.copy[prop] = value;
      state.assigned.set(assignKey, true);
      return true;
    },

    deleteProperty(_t: any, prop: PropertyKey) {
      if (typeof prop === "symbol") return true;

      if (isArr) {
        // For arrays, treat delete as setting undefined (matches Immer behavior)
        const assignKey = Number(prop as string);
        if (!state.modified) {
          prepareCopy(state);
          markChanged(state);
        }
        state.copy[prop] = undefined;
        state.assigned.set(assignKey, true);
        return true;
      }

      prepareCopy(state);
      const key = prop as string;
      if ((prop as string) in state.base) {
        state.assigned.set(key, false);
        markChanged(state);
      } else {
        state.assigned.delete(key);
      }
      if (state.copy) delete state.copy[prop];
      return true;
    },

    has(_t: any, prop: PropertyKey) {
      return prop in latest(state);
    },

    ownKeys() {
      return Reflect.ownKeys(latest(state));
    },

    getOwnPropertyDescriptor(_t: any, prop: PropertyKey) {
      const source = latest(state);
      const desc = Reflect.getOwnPropertyDescriptor(source, prop);
      if (!desc) return desc;
      return {
        writable: true,
        configurable: !(isArr && prop === "length"),
        enumerable: desc.enumerable,
        value: source[prop],
      };
    },

    getPrototypeOf() {
      return Object.getPrototypeOf(state.base);
    },

    setPrototypeOf() {
      throw new Error("Cannot set prototype on draft");
    },

    defineProperty() {
      throw new Error("Cannot define property on draft");
    },
  };

  const { proxy, revoke } = Proxy.revocable(target, handler);
  state.draft = proxy;
  state.revoke = revoke;
  return proxy;
}

function collectStates(
  state: DraftState,
  result: DraftState[] = []
): DraftState[] {
  result.push(state);
  const source = latest(state);
  const keys: (string | number)[] = Array.isArray(source)
    ? Array.from({ length: source.length }, (_, i) => i)
    : Object.keys(source);
  for (const key of keys) {
    const val = source[key];
    if (val && typeof val === "object") {
      const cs: DraftState | undefined = val[DRAFT_STATE];
      if (cs) collectStates(cs, result);
    }
  }
  return result;
}

function finalizeDraft(state: DraftState): any {
  if (state.finalized) return state.copy ?? state.base;
  state.finalized = true;

  if (!state.modified) return state.base;

  const result = state.copy!;
  const keys: (string | number)[] =
    state.type === "array"
      ? Array.from({ length: result.length }, (_, i) => i)
      : Object.keys(result);

  for (const key of keys) {
    const val = result[key];
    if (val && typeof val === "object") {
      const cs: DraftState | undefined = val[DRAFT_STATE];
      if (cs) {
        result[key] = finalizeDraft(cs);
      }
    }
  }
  return result;
}

// === Patch generation ===

function generateObjectPatches(
  state: DraftState,
  basePath: (string | number)[],
  patches: Patch[],
  inversePatches: Patch[]
): void {
  const { base, copy, assigned } = state;
  assigned.forEach((isSet, key) => {
    const origValue = base[key];
    const newValue = copy[key];
    const op: Patch["op"] = !isSet
      ? "remove"
      : key in base
        ? "replace"
        : "add";
    if (origValue === newValue && op === "replace") return;
    const path = basePath.concat(key);
    if (op === "remove") {
      patches.push({ op, path });
      inversePatches.push({ op: "add", path, value: cloneValue(origValue) });
    } else if (op === "add") {
      patches.push({ op, path, value: cloneValue(newValue) });
      inversePatches.push({ op: "remove", path });
    } else {
      patches.push({ op, path, value: cloneValue(newValue) });
      inversePatches.push({
        op: "replace",
        path,
        value: cloneValue(origValue),
      });
    }
  });
}

function generateArrayPatches(
  state: DraftState,
  basePath: (string | number)[],
  patches: Patch[],
  inversePatches: Patch[]
): void {
  let base = state.base;
  let copy = state.copy!;
  const { assigned } = state;

  // Swap when copy is shorter, simplifying remove-to-add transformation
  if (copy.length < base.length) {
    [base, copy] = [copy, base];
    [patches, inversePatches] = [inversePatches, patches];
  }

  // Replaced indices
  for (let i = 0; i < base.length; i++) {
    if (assigned.get(i) && copy[i] !== base[i]) {
      const cs: DraftState | undefined = copy[i]?.[DRAFT_STATE];
      if (cs && cs.modified) continue; // child generates own patches
      const path = basePath.concat(i);
      patches.push({ op: "replace", path, value: cloneValue(copy[i]) });
      inversePatches.push({
        op: "replace",
        path,
        value: cloneValue(base[i]),
      });
    }
  }

  // Added indices
  for (let i = base.length; i < copy.length; i++) {
    patches.push({
      op: "add",
      path: basePath.concat(i),
      value: cloneValue(copy[i]),
    });
  }

  // Inverse: remove added indices in reverse order
  for (let i = copy.length - 1; i >= base.length; i--) {
    inversePatches.push({ op: "remove", path: basePath.concat(i) });
  }
}

function walkPatches(
  state: DraftState,
  basePath: (string | number)[],
  patches: Patch[],
  inversePatches: Patch[]
): void {
  if (!state.modified) return;

  if (state.type === "array") {
    generateArrayPatches(state, basePath, patches, inversePatches);
  } else {
    generateObjectPatches(state, basePath, patches, inversePatches);
  }

  // Recurse into modified child drafts
  const source = latest(state);
  const keys: (string | number)[] =
    state.type === "array"
      ? Array.from({ length: source.length }, (_, i) => i)
      : Object.keys(source);

  for (const key of keys) {
    const val = source[key];
    if (val && typeof val === "object") {
      const cs: DraftState | undefined = val[DRAFT_STATE];
      if (cs && cs.modified) {
        walkPatches(cs, basePath.concat(key), patches, inversePatches);
      }
    }
  }
}

// === Public API ===

export function produce<T extends object>(base: T, recipe: Recipe<T>): T {
  const draft = createDraft(base, null, null);
  let result: any;
  try {
    result = recipe(draft);
  } catch (e) {
    const states = collectStates(draft[DRAFT_STATE]);
    for (const s of states) s.revoke?.();
    throw e;
  }

  const rootState: DraftState = draft[DRAFT_STATE];
  // Collect states before finalization so child proxies can be revoked
  const states = collectStates(rootState);

  let finalResult: T;
  if (result !== undefined && result !== draft) {
    finalResult = result as T;
  } else {
    finalResult = finalizeDraft(rootState) as T;
  }

  for (const s of states) s.revoke?.();
  deepFreeze(finalResult);
  return finalResult;
}

export function produceWithPatches<T extends object>(
  base: T,
  recipe: Recipe<T>
): [T, Patch[], Patch[]] {
  const draft = createDraft(base, null, null);
  let result: any;
  try {
    result = recipe(draft);
  } catch (e) {
    const states = collectStates(draft[DRAFT_STATE]);
    for (const s of states) s.revoke?.();
    throw e;
  }

  const rootState: DraftState = draft[DRAFT_STATE];
  // Collect states before finalization so child proxies can be revoked
  const states = collectStates(rootState);
  const patches: Patch[] = [];
  const inversePatches: Patch[] = [];

  let finalResult: T;
  if (result !== undefined && result !== draft) {
    finalResult = result as T;
    patches.push({
      op: "replace",
      path: [],
      value: cloneValue(finalResult),
    });
    inversePatches.push({ op: "replace", path: [], value: cloneValue(base) });
  } else {
    // Generate patches before finalization (while drafts are alive)
    walkPatches(rootState, [], patches, inversePatches);
    finalResult = finalizeDraft(rootState) as T;
  }

  for (const s of states) s.revoke?.();
  deepFreeze(finalResult);
  return [finalResult, patches, inversePatches];
}


import { createSignal, batch, untrack } from './reactive';
import type { Getter, Setter } from './reactive';

type Path = (string | number)[];

export type SetStoreFunction<T> = {
  (...args: [...Path, any]): void;
};

export function createStore<T extends object>(initial: T): [T, SetStoreFunction<T>] {
  const raw: any = JSON.parse(JSON.stringify(initial));
  const signals = new Map<string, [Getter<any>, Setter<any>]>();
  const proxyCache = new Map<string, any>();

  function getSignal(pathStr: string, initVal: any): [Getter<any>, Setter<any>] {
    if (!signals.has(pathStr)) {
      signals.set(pathStr, createSignal(initVal));
    }
    return signals.get(pathStr)!;
  }

  function makeProxy(obj: any, basePath: string): any {
    if (obj === null || typeof obj !== 'object') return obj;
    const cacheKey = basePath || '$';
    if (proxyCache.has(cacheKey)) return proxyCache.get(cacheKey);

    const p: any = new Proxy(obj, {
      get(target: any, prop: string | symbol) {
        if (typeof prop === 'symbol') return Reflect.get(target, prop);
        const key = String(prop);
        const fullPath = basePath ? `${basePath}.${key}` : key;
        const [read] = getSignal(fullPath, target[key]);
        const value = read();
        if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
          return makeProxy(value, fullPath);
        }
        return value;
      },
      set() {
        return false;
      }
    });

    proxyCache.set(cacheKey, p);
    return p;
  }

  const store = makeProxy(raw, '') as T;

  function setNestedValue(pathKeys: Path, value: any): void {
    let current = raw;
    for (let i = 0; i < pathKeys.length - 1; i++) {
      current = current[pathKeys[i]];
    }
    const lastKey = String(pathKeys[pathKeys.length - 1]);
    const resolved = typeof value === 'function' ? value(current[lastKey]) : value;
    current[lastKey] = resolved;

    const pathStr = pathKeys.map(String).join('.');
    const [, write] = getSignal(pathStr, undefined);
    write(resolved);

    if (resolved !== null && typeof resolved === 'object') {
      for (const [k, [, w]] of signals) {
        if (k.startsWith(pathStr + '.')) {
          const rel = k.slice(pathStr.length + 1);
          let v: any = resolved;
          for (const seg of rel.split('.')) {
            if (v == null || typeof v !== 'object') { v = undefined; break; }
            v = v[seg];
          }
          w(v);
        }
      }
      for (const k of [...proxyCache.keys()]) {
        if (k === pathStr || k.startsWith(pathStr + '.')) {
          proxyCache.delete(k);
        }
      }
    }
  }

  function makeDraft(obj: any, basePath: string): any {
    return new Proxy(obj, {
      get(target: any, prop: string | symbol) {
        if (typeof prop === 'symbol') return Reflect.get(target, prop);
        const val = target[String(prop)];
        if (val !== null && typeof val === 'object' && !Array.isArray(val)) {
          return makeDraft(val, basePath ? `${basePath}.${String(prop)}` : String(prop));
        }
        return val;
      },
      set(target: any, prop: string | symbol, val: any) {
        if (typeof prop === 'symbol') return Reflect.set(target, prop, val);
        const key = String(prop);
        const fullPath = basePath ? `${basePath}.${key}` : key;
        target[key] = val;
        const [, w] = getSignal(fullPath, undefined);
        w(val);
        for (const k of [...proxyCache.keys()]) {
          if (k === fullPath || k.startsWith(fullPath + '.')) proxyCache.delete(k);
        }
        return true;
      }
    });
  }

  const setStore: SetStoreFunction<T> = (...args: any[]) => {
    if (args.length === 1 && typeof args[0] === 'function') {
      batch(() => {
        const draft = makeDraft(raw, '');
        args[0](draft);
      });
      return;
    }
    const value = args[args.length - 1];
    const pathKeys: Path = args.slice(0, -1);
    if (pathKeys.length === 0) return;
    batch(() => setNestedValue(pathKeys, value));
  };

  return [store, setStore];
}

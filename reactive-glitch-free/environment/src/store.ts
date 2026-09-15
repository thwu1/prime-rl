
import { createSignal, batch, untrack } from './reactive';
import type { Getter, Setter } from './reactive';

type Path = (string | number)[];

export type SetStoreFunction<T> = {
  (...args: [...Path, any]): void;
};

export function createStore<T extends object>(initial: T): [T, SetStoreFunction<T>] {
  const raw: any = JSON.parse(JSON.stringify(initial));
  const signals = new Map<string, [Getter<any>, Setter<any>]>();

  function getSignal(pathStr: string, initVal: any): [Getter<any>, Setter<any>] {
    if (!signals.has(pathStr)) {
      signals.set(pathStr, createSignal(initVal));
    }
    return signals.get(pathStr)!;
  }

  function makeProxy(obj: any, basePath: string): any {
    if (obj === null || typeof obj !== 'object') return obj;
    return new Proxy(obj, {
      get(target: any, prop: string | symbol) {
        if (typeof prop === 'symbol') return Reflect.get(target, prop);
        // reads directly from target — no reactive tracking
        return target[String(prop)];
      },
      set(target: any, prop: string | symbol, val: any) {
        if (typeof prop === 'symbol') return Reflect.set(target, prop, val);
        // writes directly to target, bypasses signal system
        target[String(prop)] = val;
        return true;
      }
    });
  }

  const store = makeProxy(raw, '') as T;

  const setStore: SetStoreFunction<T> = (...args: any[]) => {
    if (args.length === 1 && typeof args[0] === 'function') {
      args[0](store);
      return;
    }
    const value = args[args.length - 1];
    const path: Path = args.slice(0, -1);
    if (path.length === 0) return;

    // only handles single top-level key, ignores nested paths
    const key = String(path[0]);
    const [, write] = getSignal(key, undefined);
    raw[key] = value;
    write(value);
  };

  return [store, setStore];
}

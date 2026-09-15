#!/usr/bin/env python3
"""
Fix the broken sigil.d.ts declaration file.

Bugs in the original:
1. export default instead of export = (breaks CJS consumers)
2. set() and on() return Signal<T> instead of 'this' (breaks fluent subclass chains)
3. subscribe callback return type 'any' instead of 'void'
4. subscribe callback index parameter optional instead of required
5. General pipe overload before specific string-literal overloads
6. Interface merging conflict: second Signal block has name: number vs string
7. Operator<T, U, V> has unused generic V
8. Missing export as namespace sigil (UMD global not accessible)
"""


FIXED_DECLARATION = '''\
// Type declarations for sigil reactive signal library

declare function sigil<T = unknown>(name: string): sigil.Signal<T>;

declare namespace sigil {
  interface Signal<T> {
    readonly name: string;
    get(): T | undefined;
    set(value: T): this;
    subscribe(listener: (value: T, index: number) => void): Subscription;

    pipe<U>(op: "map", fn: (value: T) => U): Signal<U>;
    pipe(op: "filter", predicate: (value: T) => boolean): Signal<T>;
    pipe(op: "debounce", ms: number): Signal<T>;
    pipe(op: "take", count: number): Signal<T>;
    pipe<U>(op: "scan", reducer: (acc: U, value: T) => U, seed: U): Signal<U>;
    pipe(op: string, ...args: unknown[]): Signal<unknown>;

    on(event: string, handler: (data: any) => void): this;
  }

  interface SignalOptions {
    lazy?: boolean;
    replay?: boolean;
    bufferSize?: number;
  }

  interface Subscription {
    unsubscribe(): void;
    readonly closed: boolean;
  }

  interface Operator<T, U> {
    (input: Signal<T>): Signal<U>;
  }

  function combine<T extends unknown[]>(
    ...signals: { [K in keyof T]: Signal<T[K]> }
  ): Signal<T>;

  function fromEvent(
    target: { addEventListener: Function },
    eventName: string
  ): Signal<unknown>;

  function fromPromise<T>(promise: PromiseLike<T>): Signal<T>;

  const EMPTY: Signal<never>;
  const version: string;
}

export as namespace sigil;
export = sigil;
'''

with open('/app/lib/sigil.d.ts', 'w') as f:
    f.write(FIXED_DECLARATION)

print("sigil.d.ts fixed successfully")

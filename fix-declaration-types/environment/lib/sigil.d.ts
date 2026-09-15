// Type declarations for sigil reactive signal library

declare function sigil<T = unknown>(name: string): sigil.Signal<T>;

declare namespace sigil {
  interface Signal<T> {
    readonly name: string;
    get(): T | undefined;
    set(value: T): Signal<T>;
    subscribe(listener: (value: T, index?: number) => any): Subscription;

    pipe(op: string, ...args: unknown[]): Signal<unknown>;
    pipe<U>(op: "map", fn: (value: T) => U): Signal<U>;
    pipe(op: "filter", predicate: (value: T) => boolean): Signal<T>;
    pipe(op: "debounce", ms: number): Signal<T>;
    pipe(op: "take", count: number): Signal<T>;
    pipe<U>(op: "scan", reducer: (acc: U, value: T) => U, seed: U): Signal<U>;

    on(event: string, handler: (data: any) => void): Signal<T>;
  }

  interface Signal<T> {
    readonly name: number;
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

  interface Operator<T, U, V> {
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

export default sigil;

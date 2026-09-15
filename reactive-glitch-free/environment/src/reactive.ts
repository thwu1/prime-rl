
export type Getter<T> = () => T;
export type Setter<T> = (value: T | ((prev: T) => T)) => void;

// --- Internal types ---
interface Computation {
  fn: (() => void) | null;
  execute: () => void;
  dependencies: Set<Set<Computation>>;
}

// --- Global context stack for auto-tracking ---
const context: (Computation | null)[] = [];

function subscribe(running: Computation, subscriptions: Set<Computation>) {
  subscriptions.add(running);
  running.dependencies.add(subscriptions);
}

function cleanupDeps(running: Computation) {
  for (const dep of running.dependencies) {
    dep.delete(running);
  }
  running.dependencies.clear();
}

// --- Public API ---

export function createSignal<T>(value: T): [Getter<T>, Setter<T>] {
  const subscriptions = new Set<Computation>();

  const read: Getter<T> = () => {
    const running = context[context.length - 1];
    if (running) subscribe(running, subscriptions);
    return value;
  };

  const write: Setter<T> = (nextValue) => {
    const newVal =
      typeof nextValue === "function"
        ? (nextValue as (prev: T) => T)(value)
        : nextValue;
    if (Object.is(newVal, value)) return;
    value = newVal;
    for (const sub of [...subscriptions]) {
      sub.execute();
    }
  };

  return [read, write];
}

export function createEffect(fn: () => void): void {
  const execute = () => {
    cleanupDeps(running);
    context.push(running);
    try {
      fn();
    } finally {
      context.pop();
    }
  };

  const running: Computation = {
    fn,
    execute,
    dependencies: new Set(),
  };

  execute();
}

export function createMemo<T>(fn: () => T): Getter<T> {
  const [s, set] = createSignal<T>(undefined as unknown as T);
  createEffect(() => set(fn()));
  return s;
}

export function batch(fn: () => void): void {
  fn();
}

export function createRoot<T>(fn: (dispose: () => void) => T): T {
  return fn(() => {});
}

export function untrack<T>(fn: () => T): T {
  return fn();
}

export function onCleanup(fn: () => void): void {
  // not implemented
}

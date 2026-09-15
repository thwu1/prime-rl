
// Fine-grained reactive system with push-based dependency tracking.

const CLEAN = 0;
const STALE = 1;
const PENDING = 2;

const defaultEq = <T>(a: T, b: T): boolean => a === b;

// --- Public Types ---

export type Accessor<T> = () => T;
export type Setter<T> = {
  (value: Exclude<T, Function>): T;
  (fn: (prev: T) => T): T;
};
export type Signal<T> = [Accessor<T>, Setter<T>];
export type SignalOptions<T> = {
  equals?: false | ((prev: T, next: T) => boolean);
};

// --- Internal Types ---

interface SignalNode<T = any> {
  value: T;
  observers: Computation[] | null;
  observerSlots: number[] | null;
  comparator?: (prev: T, next: T) => boolean;
}

interface Owner {
  owned: Computation[] | null;
  cleanups: (() => void)[] | null;
  owner: Owner | null;
}

interface Computation<T = any> extends Owner {
  fn: ((v: T) => T) | null;
  state: number;
  sources: SignalNode[] | null;
  sourceSlots: number[] | null;
  value: T;
  pure: boolean;
  updatedAt: number | null;
}

interface Memo<T = any> extends Computation<T> {
  observers: Computation[] | null;
  observerSlots: number[] | null;
  comparator?: (prev: T, next: T) => boolean;
}

// --- Global State ---

let Listener: Computation | null = null;
let CurOwner: Owner | null = null;
let Updates: Computation[] | null = null;
let Effects: Computation[] | null = null;
let ExecCount = 0;

// --- Public API ---

export function createRoot<T>(fn: (dispose: () => void) => T): T {
  const prevListener = Listener;
  const prevOwner = CurOwner;
  const root: Owner = {
    owned: null,
    cleanups: null,
    owner: prevOwner
  };
  CurOwner = root;
  Listener = null;
  try {
    return runUpdates(
      () => fn(() => untrack(() => cleanNode(root))),
      true
    )!;
  } finally {
    Listener = prevListener;
    CurOwner = prevOwner;
  }
}

export function createSignal<T>(
  value: T,
  options?: SignalOptions<T>
): Signal<T> {
  const node: SignalNode<T> = {
    value,
    observers: null,
    observerSlots: null,
    comparator:
      options?.equals === false
        ? undefined
        : (options?.equals ?? defaultEq)
  };

  const read: Accessor<T> = () => readSignal(node);
  const write = ((v: any) => {
    const val = typeof v === "function" ? v(node.value) : v;
    return writeSignal(node, val);
  }) as Setter<T>;

  return [read, write];
}

export function createMemo<T>(
  fn: (prev: T) => T,
  value?: T,
  options?: SignalOptions<T>
): Accessor<T> {
  const c = createComputation(fn, value!, true, STALE) as Memo<T>;
  c.observers = null;
  c.observerSlots = null;
  c.comparator =
    options?.equals === false
      ? undefined
      : (options?.equals ?? defaultEq);
  updateComputation(c);
  return (() => readSignal(c)) as Accessor<T>;
}

export function createEffect<T>(
  fn: (prev: T) => T,
  value?: T
): void {
  const c = createComputation(fn, value!, false, STALE);
  if (Effects) Effects.push(c);
  else updateComputation(c);
}

export function batch<T>(fn: () => T): T {
  return fn();
}

export function untrack<T>(fn: () => T): T {
  const prev = Listener;
  Listener = null;
  try {
    return fn();
  } finally {
    Listener = prev;
  }
}

export function onCleanup(fn: () => void): void {
  if (CurOwner) {
    if (!CurOwner.cleanups) CurOwner.cleanups = [fn];
    else CurOwner.cleanups.push(fn);
  }
}

// --- Internal Implementation ---

function readSignal<T>(node: SignalNode<T> & Partial<Memo<T>>): T {
  if (
    (node as Computation).sources &&
    (node as Computation).state
  ) {
    if ((node as Computation).state === STALE) {
      updateComputation(node as Computation);
    }
  }
  if (Listener) {
    const observers = node.observers;
    if (
      !observers ||
      observers[observers.length - 1] !== Listener
    ) {
      const sSlot = observers ? observers.length : 0;
      if (!Listener.sources) {
        Listener.sources = [node];
        Listener.sourceSlots = [sSlot];
      } else {
        Listener.sources.push(node);
        Listener.sourceSlots!.push(sSlot);
      }
      if (!observers) {
        node.observers = [Listener];
        node.observerSlots = [Listener.sources.length - 1];
      } else {
        observers.push(Listener);
        node.observerSlots!.push(Listener.sources.length - 1);
      }
    }
  }
  return node.value;
}

function writeSignal(node: SignalNode, value: any): any {
  if (!node.comparator || !node.comparator(node.value, value)) {
    node.value = value;
    if (node.observers && node.observers.length) {
      runUpdates(() => {
        for (let i = 0; i < node.observers!.length; i++) {
          const o = node.observers![i];
          if (!o.state) {
            if (o.pure) Updates!.push(o);
            else Effects!.push(o);
            if ((o as Memo).observers) markDownstream(o as Memo);
          }
          o.state = STALE;
        }
        if (Updates!.length > 1e6) {
          Updates = [];
          throw new Error("Potential Infinite Loop Detected.");
        }
      }, false);
    }
  }
  return value;
}

function markDownstream(node: Memo): void {
  if (!node.observers) return;
  for (let i = 0; i < node.observers.length; i++) {
    const o = node.observers[i];
    if (!o.state) {
      o.state = STALE;
      if (o.pure) Updates!.push(o);
      else Effects!.push(o);
      if ((o as Memo).observers) markDownstream(o as Memo);
    }
  }
}

function createComputation<T>(
  fn: (v: T) => T,
  init: T,
  pure: boolean,
  state: number
): Computation<T> {
  const c: Computation<T> = {
    fn,
    state,
    value: init,
    pure,
    sources: null,
    sourceSlots: null,
    owned: null,
    cleanups: null,
    owner: CurOwner,
    updatedAt: null
  };
  if (CurOwner) {
    if (!CurOwner.owned) CurOwner.owned = [c];
    else CurOwner.owned.push(c);
  }
  return c;
}

function updateComputation(node: Computation): void {
  if (!node.fn) return;
  cleanNode(node);
  const time = ExecCount;
  runComputation(node, node.value, time);
}

function runComputation(
  node: Computation,
  value: any,
  time: number
): void {
  const prevOwner = CurOwner;
  const prevListener = Listener;
  Listener = CurOwner = node;
  let nextValue: any;
  try {
    nextValue = node.fn!(value);
  } catch (err) {
    if (node.pure) {
      node.state = STALE;
      if (node.owned) {
        node.owned.forEach((n) => cleanNode(n));
        node.owned = null;
      }
    }
    node.updatedAt = time + 1;
    throw err;
  } finally {
    Listener = prevListener;
    CurOwner = prevOwner;
  }
  if (!node.updatedAt || node.updatedAt <= time) {
    if (node.updatedAt != null && "observers" in node) {
      writeSignal(node as Memo, nextValue);
    } else {
      node.value = nextValue;
    }
    node.updatedAt = time;
  }
}

function cleanNode(node: Owner): void {
  if (node.owned) {
    for (let i = node.owned.length - 1; i >= 0; i--) {
      cleanNode(node.owned[i]);
    }
    node.owned = null;
  }
  if (node.cleanups) {
    for (let i = node.cleanups.length - 1; i >= 0; i--) {
      node.cleanups[i]();
    }
    node.cleanups = null;
  }
  (node as Computation).state = CLEAN;
}

function runTop(node: Computation): void {
  if (node.state === CLEAN) return;
  updateComputation(node);
}

function runQueue(queue: Computation[]): void {
  for (let i = 0; i < queue.length; i++) {
    runTop(queue[i]);
  }
}

function runUpdates<T>(
  fn: () => T,
  init: boolean
): T | undefined {
  if (Updates) return fn();
  let wait = false;
  if (!init) Updates = [];
  if (Effects) wait = true;
  else Effects = [];
  ExecCount++;
  try {
    const res = fn();
    completeUpdates(wait);
    return res;
  } catch (err) {
    if (!wait) Effects = null;
    Updates = null;
    throw err;
  }
}

function completeUpdates(wait: boolean): void {
  if (Updates) {
    runQueue(Updates);
    Updates = null;
  }
  if (wait) return;
  const e = Effects!;
  Effects = null;
  if (e.length) runUpdates(() => runEffects(e), false);
}

function runEffects(queue: Computation[]): void {
  for (let i = 0; i < queue.length; i++) {
    runTop(queue[i]);
  }
}

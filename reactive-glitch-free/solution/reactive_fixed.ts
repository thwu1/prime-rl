
export type Getter<T> = () => T;
export type Setter<T> = (value: T | ((prev: T) => T)) => void;

// ── Push-pull state constants ──────────────────────────────────────

const CLEAN: number = 0;
const STALE: number = 1;
const PENDING: number = 2;

// ── Core types ─────────────────────────────────────────────────────

interface Source {
  value: any;
  observers: Computation[];
}

interface Computation {
  fn: (() => any) | null;
  state: number;
  sources: Source[];
  owned: Computation[];
  cleanups: (() => void)[];
  owner: Computation | null;
}

type MemoNode = Computation & Source;

// ── Runtime state ──────────────────────────────────────────────────

let Listener: Computation | null = null;
let Owner: Computation | null = null;
let PendingEffects: Computation[] = [];
let BatchDepth = 0;
let Flushing = false;

// ── Type guards ────────────────────────────────────────────────────

function isCompMemo(node: Computation): node is MemoNode {
  return Array.isArray((node as any).observers);
}

function isSourceMemo(node: Source): node is MemoNode {
  return "fn" in node;
}

// ── Dependency tracking ────────────────────────────────────────────

function trackSource(source: Source): void {
  if (!Listener) return;
  if (Listener.sources.indexOf(source) === -1) {
    Listener.sources.push(source);
    source.observers.push(Listener);
  }
}

function cleanSources(comp: Computation): void {
  for (const src of comp.sources) {
    const idx = src.observers.indexOf(comp);
    if (idx !== -1) src.observers.splice(idx, 1);
  }
  comp.sources = [];
}

// ── Cleanup and disposal ───────────────────────────────────────────

function runCleanups(comp: Computation): void {
  for (const fn of comp.cleanups) fn();
  comp.cleanups = [];
}

function disposeNode(comp: Computation): void {
  for (const child of comp.owned) disposeNode(child);
  cleanSources(comp);
  runCleanups(comp);
  comp.owned = [];
  comp.fn = null;
}

// ── Push phase ─────────────────────────────────────────────────────

function notifyObservers(source: Source): void {
  for (const obs of source.observers.slice()) {
    if (obs.state === CLEAN) {
      if (isCompMemo(obs)) {
        obs.state = STALE;
        propagatePending(obs);
      } else {
        obs.state = STALE;
        enqueueEffect(obs);
      }
    }
  }
}

function propagatePending(memo: MemoNode): void {
  for (const obs of memo.observers.slice()) {
    if (obs.state === CLEAN) {
      obs.state = PENDING;
      if (isCompMemo(obs)) {
        propagatePending(obs);
      } else {
        enqueueEffect(obs);
      }
    }
  }
}

function enqueueEffect(effect: Computation): void {
  if (PendingEffects.indexOf(effect) === -1) {
    PendingEffects.push(effect);
  }
}

// ── Pull phase ─────────────────────────────────────────────────────

function updateComputation(comp: Computation): void {
  if (comp.state === CLEAN) return;

  if (comp.state === PENDING) {
    for (const src of comp.sources) {
      if (isSourceMemo(src) && (src as Computation).state !== CLEAN) {
        updateComputation(src as Computation);
        if (comp.state === STALE) break;
      }
    }
    if (comp.state === PENDING) {
      comp.state = CLEAN;
      return;
    }
  }

  for (const child of comp.owned) disposeNode(child);
  comp.owned = [];
  runCleanups(comp);
  cleanSources(comp);

  const prevListener = Listener;
  const prevOwner = Owner;
  Listener = comp;
  Owner = comp;

  try {
    if (isCompMemo(comp)) {
      const prevValue = comp.value;
      const newValue = comp.fn!();
      comp.state = CLEAN;

      if (!Object.is(prevValue, newValue)) {
        comp.value = newValue;
        for (const obs of comp.observers) {
          if (obs.state === PENDING) {
            obs.state = STALE;
          }
        }
      }
    } else {
      comp.fn!();
      comp.state = CLEAN;
    }
  } finally {
    Listener = prevListener;
    Owner = prevOwner;
  }
}

// ── Effect queue flush ─────────────────────────────────────────────

function flushEffects(): void {
  if (Flushing) return;
  Flushing = true;
  try {
    let safety = 1000;
    while (PendingEffects.length > 0) {
      if (--safety < 0) {
        throw new Error("Reactive cycle detected: too many update rounds");
      }
      const queue = PendingEffects;
      PendingEffects = [];
      for (const effect of queue) {
        if (effect.state !== CLEAN && effect.fn) {
          updateComputation(effect);
        }
      }
    }
  } finally {
    Flushing = false;
  }
}

// ═══════════════════════════════════════════════════════════════════
// PUBLIC API
// ═══════════════════════════════════════════════════════════════════

export function createSignal<T>(value: T): [Getter<T>, Setter<T>] {
  const node: Source = { value, observers: [] };

  const read: Getter<T> = () => {
    trackSource(node);
    return node.value;
  };

  const write: Setter<T> = (nextValue) => {
    const newVal =
      typeof nextValue === "function"
        ? (nextValue as (prev: T) => T)(node.value)
        : nextValue;
    if (Object.is(newVal, node.value)) return;
    node.value = newVal;
    notifyObservers(node);
    if (BatchDepth === 0) flushEffects();
  };

  return [read, write];
}

export function createEffect(fn: () => void): void {
  const comp: Computation = {
    fn,
    state: STALE,
    sources: [],
    owned: [],
    cleanups: [],
    owner: Owner,
  };
  if (Owner) Owner.owned.push(comp);
  updateComputation(comp);
}

export function createMemo<T>(fn: () => T): Getter<T> {
  const comp: MemoNode = {
    fn,
    state: STALE,
    sources: [],
    owned: [],
    cleanups: [],
    owner: Owner,
    value: undefined as T,
    observers: [],
  };
  if (Owner) Owner.owned.push(comp);
  updateComputation(comp);

  return () => {
    if (comp.state !== CLEAN) updateComputation(comp);
    trackSource(comp);
    return comp.value;
  };
}

export function batch(fn: () => void): void {
  BatchDepth++;
  try {
    fn();
  } finally {
    BatchDepth--;
    if (BatchDepth === 0) flushEffects();
  }
}

export function createRoot<T>(fn: (dispose: () => void) => T): T {
  const root: Computation = {
    fn: null,
    state: CLEAN,
    sources: [],
    owned: [],
    cleanups: [],
    owner: Owner,
  };

  const prevOwner = Owner;
  Owner = root;
  try {
    return fn(() => disposeNode(root));
  } finally {
    Owner = prevOwner;
  }
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
  if (Owner) Owner.cleanups.push(fn);
}

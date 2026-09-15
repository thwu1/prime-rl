
import sigil = require('sigil');
import '../plugins/sigil-persist';

// ---- 1. persist returns this for fluent chaining ----
const s = sigil<number>('counter');
s.persist('counter-key').set(42);

// ---- 2. persist with custom serializer (structural match) ----
s.persist('custom-key', {
  serialize: (v: number) => String(v),
  deserialize: (raw: string) => Number(raw)
});

// ---- 3. restore returns this, accepts optional typed fallback ----
s.restore(0).set(100);
const s2 = sigil<string>('name');
s2.restore('default');

// ---- 4. snapshot returns typed object ----
const snap = s.snapshot();
const snapKey: string = snap.key;
const snapValue: number | undefined = snap.value;
const snapTime: number = snap.timestamp;
const snapDirty: boolean = snap.dirty;

// ---- 5. derived creates a new signal via transform ----
const desc = s.derived((val, sn) => `${sn.key}=${val}`);
const _descCheck: sigil.Signal<string> = desc;

const doubled = s.derived((val) => (val ?? 0) * 2);
const _doubledCheck: sigil.Signal<number> = doubled;

// ---- 6. Augmented methods preserve polymorphic this on subtypes ----
interface TrackedSignal<T> extends sigil.Signal<T> {
  track(): void;
}
declare function createTracked<T>(name: string): TrackedSignal<T>;
const tracked = createTracked<number>('t');
tracked.persist('t-key').track();
tracked.restore(0).track();
tracked.persist('t-key').set(1).on('change', () => {});

// ---- Negative tests ----

// @ts-expect-error - persist requires string key, not number
s.persist(42);

// @ts-expect-error - snapshot().value is T | undefined, not T
const _snapBad: number = s.snapshot().value;

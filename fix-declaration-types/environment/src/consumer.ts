
import sigil = require('sigil');

// ---- 1. Callable factory with generics ----
const counter = sigil<number>('counter');
const named = sigil<string>('name');
const withOpts = sigil<number>('count', { lazy: true });

// ---- 2. Property access ----
const nm: string = counter.name;

// ---- 3. Basic read API ----
const val: number | undefined = counter.get();
const peeked: number | undefined = counter.peek();

// ---- 4. Set returns this for chaining ----
counter.set(42);

// ---- 5. Update with function, returns this ----
counter.update((current: number | undefined) => (current ?? 0) + 1);

// ---- 6. Subscription: (value: T, index: number) => void ----
const sub: sigil.Subscription = counter.subscribe((value: number, index: number) => {
  console.log(value, index);
});
sub.unsubscribe();
const closed: boolean = sub.closed;

// ---- 7. Verify listener return is void, not any ----
type ListenerType = Parameters<sigil.Signal<number>['subscribe']>[0];
type ListenerReturn = ReturnType<ListenerType>;
// @ts-expect-error - void is not assignable to string; if return were 'any', this would not error
const _voidCheck: string = null! as ListenerReturn;

// ---- 8. Verify index parameter is required (not optional) ----
type IndexType = Parameters<ListenerType>[1];
const _indexRequired: number = null! as IndexType;

// ---- 9. Pipe overloads: string-literal operators ----
const mapped = counter.pipe("map", (n: number) => n.toString());
const _mapCheck: sigil.Signal<string> = mapped;

const filtered = counter.pipe("filter", (n: number) => n > 0);
const _filterCheck: sigil.Signal<number> = filtered;

const debounced = counter.pipe("debounce", 300);
const _debounceCheck: sigil.Signal<number> = debounced;

const taken = counter.pipe("take", 5);
const _takeCheck: sigil.Signal<number> = taken;

const scanned = counter.pipe("scan", (acc: number, v: number) => acc + v, 0);
const _scanCheck: sigil.Signal<number> = scanned;

const switchMapped = counter.pipe("switchMap", (n: number) => sigil<string>('inner'));
const _switchMapCheck: sigil.Signal<string> = switchMapped;

const paired = counter.pipe("pairwise");
const _pairCheck: sigil.Signal<[number, number]> = paired;

const distinct = counter.pipe("distinctUntilChanged");
const _distinctCheck: sigil.Signal<number> = distinct;

const custom = counter.pipe("custom-op", 1, "arg");
const _customCheck: sigil.Signal<unknown> = custom;

// ---- 10. Pipe with function operator ----
const op: sigil.Operator<number, string> = (input) => sigil<string>('op-result');
const piped = counter.pipe(op);
const _pipedCheck: sigil.Signal<string> = piped;

// ---- 11. Fluent API: set/on/update/once return this ----
interface EnhancedSignal<T> extends sigil.Signal<T> {
  enhance(): string;
}
declare function createEnhanced<T>(name: string): EnhancedSignal<T>;
const enhanced = createEnhanced<number>('test');
enhanced.set(42).enhance();
enhanced.on('change', (v: number) => {}).enhance();
enhanced.update((c) => (c ?? 0) + 1).enhance();
enhanced.once('change', (v: number) => {}).enhance();
enhanced.set(1).set(2).set(3);

// ---- 12. Typed events: handler type depends on event name ----
counter.on("change", (value: number) => { console.log(value); });
counter.on("error", (err: Error) => { console.error(err); });
counter.on("complete", () => {});
counter.once("change", (v: number) => {});
counter.once("error", (e: Error) => {});

// ---- 13. sigil.of with type inference ----
const fromVal = sigil.of(42);
const _ofCheck: sigil.Signal<number> = fromVal;
const fromStr = sigil.of("hello");
const _ofStrCheck: sigil.Signal<string> = fromStr;

// ---- 14. Computed with variadic tuple deps ----
const s1 = sigil<number>('a');
const s2 = sigil<string>('b');
const comp = sigil.computed(
  [s1, s2],
  (a: number | undefined, b: string | undefined) => `${a}-${b}`
);
const _compCheck: sigil.Signal<string> = comp;

// ---- 15. Combine preserves tuple type ----
const combined = sigil.combine(s1, s2);
const _combinedCheck: sigil.Signal<[number, string]> = combined;

// ---- 16. Merge produces union type ----
const merged = sigil.merge(s1, s2);
const _mergedCheck: sigil.Signal<number | string> = merged;

// ---- 17. Static utilities ----
const fromEvt = sigil.fromEvent({ addEventListener: () => {} }, 'click');
const fromProm = sigil.fromPromise(Promise.resolve(42));
const _promCheck: sigil.Signal<number> = fromProm;
sigil.batch(() => { counter.set(1); counter.set(2); });

// ---- 18. Constants ----
const empty = sigil.EMPTY;
const ver: string = sigil.version;


import sigil = require('sigil');

const s = sigil<number>('test');
const s2 = sigil<string>('test2');

// @ts-expect-error - cannot set wrong type on a typed signal
s.set("not a number");

// @ts-expect-error - Operator takes exactly 2 type params, not 3
const _badOp: sigil.Operator<number, string, boolean> = null!;

// @ts-expect-error - get() returns T | undefined, not T
const _definite: number = s.get();

// @ts-expect-error - EMPTY is Signal<never>, set(value: never) rejects all values
sigil.EMPTY.set(42);

// @ts-expect-error - update fn must return T, not different type
s.update((c) => "not a number");

// @ts-expect-error - merge returns Signal<A|B>, not Signal<[A,B]>
const _mergeNotTuple: sigil.Signal<[number, string]> = sigil.merge(s, s2);

// @ts-expect-error - combine returns Signal<[A,B]>, not Signal<A|B>
const _combineNotUnion: sigil.Signal<number | string> = sigil.combine(s, s2);

// @ts-expect-error - peek() returns T | undefined, not T
const _peekDefinite: number = s.peek();

// @ts-expect-error - fromPromise preserves type, Signal<number> not assignable to Signal<string>
const _promBad: sigil.Signal<string> = sigil.fromPromise(Promise.resolve(42));

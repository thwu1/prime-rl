
import { describe, it, expect, test } from 'vitest';
import SuperJSON from './index.js';

describe('Basic round-trip serialization', () => {
  test('plain objects', () => {
    const input = { a: 1, b: 'hello', c: true, d: null };
    expect(SuperJSON.deserialize(SuperJSON.serialize(input))).toEqual(input);
  });

  test('Date', () => {
    const input = { date: new Date(2024, 0, 15) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.date).toBeInstanceOf(Date);
    expect(output.date.getTime()).toBe(input.date.getTime());
  });

  test('Set', () => {
    const input = { s: new Set([1, 2, 3]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.s).toBeInstanceOf(Set);
    expect([...output.s]).toEqual([1, 2, 3]);
  });

  test('Map with string keys', () => {
    const input = { m: new Map<string, number>([['a', 1], ['b', 2]]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.m).toBeInstanceOf(Map);
    expect(output.m.get('a')).toBe(1);
    expect(output.m.get('b')).toBe(2);
  });

  test('BigInt', () => {
    const input = { n: BigInt('999999999999999999') };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.n).toBe(BigInt('999999999999999999'));
  });

  test('RegExp', () => {
    const input = { r: /hello/gi };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.r).toBeInstanceOf(RegExp);
    expect(output.r.source).toBe('hello');
    expect(output.r.flags).toBe('gi');
  });

  test('undefined in array', () => {
    const input = { a: [1, undefined, 3] };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.a[1]).toBeUndefined();
    expect(output.a[0]).toBe(1);
    expect(output.a[2]).toBe(3);
  });

  test('NaN, Infinity, -Infinity', () => {
    const input = { nan: NaN, inf: Infinity, ninf: -Infinity };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(Number.isNaN(output.nan)).toBe(true);
    expect(output.inf).toBe(Infinity);
    expect(output.ninf).toBe(-Infinity);
  });

  test('negative zero', () => {
    const input = -0;
    const parsed: number = SuperJSON.parse(SuperJSON.stringify(input));
    expect(1 / parsed).toBe(-Infinity);
  });

  test('URL', () => {
    const input = { url: new URL('https://example.com/path?q=1') };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.url).toBeInstanceOf(URL);
    expect(output.url.href).toBe('https://example.com/path?q=1');
  });

  test('Error', () => {
    const input = { e: new Error('test error') };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.e).toBeInstanceOf(Error);
    expect(output.e.message).toBe('test error');
  });

  test('Error with cause', () => {
    const input = {
      e: new Error('outer', { cause: new Error('inner') }),
    };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.e.message).toBe('outer');
    expect(output.e.cause).toBeInstanceOf(Error);
    expect(output.e.cause.message).toBe('inner');
  });

  test('Map with NaN key', () => {
    const input = { m: new Map<any, string>([[NaN, 'nan-val'], [1, 'one']]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.m).toBeInstanceOf(Map);
    expect(output.m.size).toBe(2);
    expect(output.m.get(1)).toBe('one');
    expect(output.m.get(NaN)).toBe('nan-val');
  });

  test('empty containers', () => {
    const input = { emptyMap: new Map(), emptySet: new Set(), emptyArr: [] };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.emptyMap).toBeInstanceOf(Map);
    expect(output.emptyMap.size).toBe(0);
    expect(output.emptySet).toBeInstanceOf(Set);
    expect(output.emptySet.size).toBe(0);
  });

  test('deeply nested Dates', () => {
    const date = new Date(2024, 5, 15);
    const input = { a: { b: { c: { d: date } } } };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.a.b.c.d).toBeInstanceOf(Date);
    expect(output.a.b.c.d.getTime()).toBe(date.getTime());
  });

  test('Set containing objects with Date values', () => {
    const input = { s: new Set([{ created: new Date(2024, 0, 1) }]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.s).toBeInstanceOf(Set);
    const first = [...output.s][0];
    expect(first.created).toBeInstanceOf(Date);
  });

  test('undefined as direct object property value', () => {
    const input = { defined: 'yes', undef: undefined, also: 'here' };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.defined).toBe('yes');
    expect(output.undef).toBeUndefined();
    expect(output.also).toBe('here');
  });
});

describe('Path escaping with special characters', () => {
  test('keys containing dots are escaped correctly', () => {
    const input = { 'a.1': { b: new Set([1, 2]) } };
    const { json, meta } = SuperJSON.serialize(input);
    const output: any = SuperJSON.deserialize(
      JSON.parse(JSON.stringify({ json, meta }))
    );
    expect(output['a.1'].b).toBeInstanceOf(Set);
    expect([...output['a.1'].b]).toEqual([1, 2]);
  });

  test('keys containing backslashes are escaped correctly', () => {
    const input = { 'a\\.1': { b: new Set([1, 2]) } };
    const { json, meta } = SuperJSON.serialize(input);
    const output: any = SuperJSON.deserialize(
      JSON.parse(JSON.stringify({ json, meta }))
    );
    expect(output).toHaveProperty('a\\.1');
    expect(output['a\\.1'].b).toBeInstanceOf(Set);
    expect([...output['a\\.1'].b]).toEqual([1, 2]);
  });

  test('regression #310: mixed dots and backslashes in keys', () => {
    const input = {
      a: ["/'a'[0]: a string"],
      'a.0': /'a\.0': a regex/,
      'b.0': "/'b.0': a string",
      'b\\': [/'b\\'[0]: a regex/],
    };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output['a.0']).toBeInstanceOf(RegExp);
    expect(output['b\\']).toBeInstanceOf(Array);
    expect(output['b\\'][0]).toBeInstanceOf(RegExp);
    expect(output['a'][0]).toBe("/'a'[0]: a string");
    expect(output['b.0']).toBe("/'b.0': a string");
  });
});

describe('Referential equality', () => {
  test('preserves object identity for non-root objects', () => {
    const a = { id: 'a' };
    const b = { id: 'b' };
    const input = { options: [a, b], selected: a };
    const serialized = SuperJSON.serialize(input);
    const output: any = SuperJSON.deserialize(
      JSON.parse(JSON.stringify(serialized))
    );
    expect(output.selected).toBe(output.options[0]);
    expect(output.selected.id).toBe('a');
  });

  test('self-referencing objects with root as equality target', () => {
    const a: any = { role: 'parent', children: [] as any[] };
    const b = { role: 'child', parents: [a] };
    a.children.push(b);

    const serialized = SuperJSON.serialize(a);

    // The JSON should have null at the circular reference position
    expect((serialized.json as any).children[0].parents[0]).toBeNull();

    // meta.referentialEqualities should use tuple format for root
    const refEq = serialized.meta?.referentialEqualities;
    expect(Array.isArray(refEq)).toBe(true);
    expect((refEq as any[])[0]).toContain('children.0.parents.0');

    const deserialized: any = SuperJSON.deserialize(
      JSON.parse(JSON.stringify(serialized))
    );
    expect(deserialized.role).toBe('parent');
    expect(deserialized.children[0].role).toBe('child');
    expect(deserialized.children[0].parents[0]).toBe(deserialized);
  });

  test('referential equality through Map keys', () => {
    const sharedObj = { id: 5 };
    const highscores = new Map([[sharedObj, 5000]]);
    const input = { highscores, topScorer: sharedObj } as any;

    const serialized = SuperJSON.serialize(input);
    const deserialized: any = SuperJSON.deserialize(
      JSON.parse(JSON.stringify(serialized))
    );

    expect(deserialized.highscores).toBeInstanceOf(Map);
    const mapKey = [...deserialized.highscores.keys()][0];
    expect(deserialized.topScorer).toBe(mapKey);
    expect(deserialized.topScorer.id).toBe(5);
  });

  test('shared Map reference', () => {
    const map = new Map([[1, 1]]);
    const input = { a: map, b: map };
    const serialized = SuperJSON.serialize(input);
    const output: any = SuperJSON.deserialize(
      JSON.parse(JSON.stringify(serialized))
    );
    expect(output.a).toBe(output.b);
    expect(output.a).toBeInstanceOf(Map);
  });

  test('referentially equal values inside Set', () => {
    const user = { id: 2 };
    const input = { users: new Set([user]), userOfTheMonth: user };
    const output: any = SuperJSON.deserialize(
      SuperJSON.serialize(input)
    );
    expect(output.users.values().next().value).toBe(output.userOfTheMonth);
  });

  test('referential equality across nested Maps and Sets', () => {
    const user = { id: 2 };
    const input = {
      workspaces: new Map<number, { users: Set<any> }>([
        [1, { users: new Set([user]) }],
        [2, { users: new Set([user]) }],
      ]),
    };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.workspaces).toBeInstanceOf(Map);
    const ws1Users = output.workspaces.get(1).users;
    const ws2Users = output.workspaces.get(2).users;
    expect([...ws1Users][0]).toBe([...ws2Users][0]);
  });

  test('referential equality with backslash-ending keys', () => {
    const shared = { val: 42 };
    const input: Record<string, any> = {};
    input['k\\'] = { nested: shared };
    input.ref = shared;
    const serialized = SuperJSON.serialize(input);
    const output: any = SuperJSON.deserialize(
      JSON.parse(JSON.stringify(serialized))
    );
    expect(output['k\\'].nested).toBe(output.ref);
    expect(output.ref.val).toBe(42);
  });
});

describe('Dedupe mode', () => {
  test('dedupe=true replaces duplicate objects with null in JSON', () => {
    const instance = new SuperJSON({ dedupe: true });
    const shared = { children: [] as any[] };
    const input = { a: shared, b: shared };

    const output = instance.serialize(input);
    const json = output.json as any;

    expect(json.a).toEqual({ children: [] });
    expect(json.b).toBeNull();
  });

  test('dedupe=true round-trips correctly', () => {
    const instance = new SuperJSON({ dedupe: true });
    const shared = { id: 1, data: [1, 2, 3] };
    const input = { x: shared, y: shared, z: { nested: shared } };

    const serialized = instance.serialize(input);
    const deserialized: any = instance.deserialize(serialized);

    expect(deserialized).toEqual(input);
    expect(deserialized.x).toBe(deserialized.y);
    expect(deserialized.x).toBe(deserialized.z.nested);
  });

  test('dedupe=true reduces serialized payload size', () => {
    const instance = new SuperJSON({ dedupe: true });
    const nonDedupeInstance = new SuperJSON({ dedupe: false });

    const bigObject = { data: Array.from({ length: 100 }, (_, i) => i) };
    const input = { a: bigObject, b: bigObject, c: bigObject };

    const deduped = JSON.stringify(instance.serialize(input));
    const nonDeduped = JSON.stringify(nonDedupeInstance.serialize(input));

    expect(deduped.length).toBeLessThan(nonDeduped.length);
  });
});

describe('Typed arrays', () => {
  test('Int8Array round-trip', () => {
    const input = { a: new Int8Array([1, 2, -3]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.a).toBeInstanceOf(Int8Array);
    expect([...output.a]).toEqual([1, 2, -3]);
  });

  test('Uint8ClampedArray round-trip', () => {
    const input = { a: new Uint8ClampedArray([0, 128, 255]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.a).toBeInstanceOf(Uint8ClampedArray);
    expect([...output.a]).toEqual([0, 128, 255]);
  });

  test('Float64Array with NaN and Infinity', () => {
    const input = { a: new Float64Array([NaN, 0, Infinity, -Infinity]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.a).toBeInstanceOf(Float64Array);
    expect(Number.isNaN(output.a[0])).toBe(true);
    expect(output.a[1]).toBe(0);
    expect(output.a[2]).toBe(Infinity);
    expect(output.a[3]).toBe(-Infinity);
  });

  test('BigInt64Array round-trip', () => {
    const input = { a: new BigInt64Array([1n, -2n, 9007199254740993n]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.a).toBeInstanceOf(BigInt64Array);
    expect([...output.a]).toEqual([1n, -2n, 9007199254740993n]);
  });

  test('BigUint64Array round-trip', () => {
    const input = { b: new BigUint64Array([0n, 18446744073709551615n]) };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.b).toBeInstanceOf(BigUint64Array);
    expect([...output.b]).toEqual([0n, 18446744073709551615n]);
  });

  test('serialization format for typed arrays', () => {
    const input = { a: new Int8Array([1, 2]) };
    const { json, meta } = SuperJSON.serialize(input);
    expect(json).toEqual({ a: [1, 2] });
    expect(meta?.values).toEqual({ a: [['typed-array', 'Int8Array']] });
  });

  test('multiple typed arrays in one object', () => {
    const input = {
      a: new Int8Array([1, 2]),
      b: new Uint8ClampedArray(3),
      c: new Float32Array([1.5, 2.5]),
    };
    const output: any = SuperJSON.deserialize(SuperJSON.serialize(input));
    expect(output.a).toBeInstanceOf(Int8Array);
    expect(output.b).toBeInstanceOf(Uint8ClampedArray);
    expect(output.c).toBeInstanceOf(Float32Array);
    expect([...output.a]).toEqual([1, 2]);
    expect([...output.b]).toEqual([0, 0, 0]);
  });
});

describe('Prototype pollution protection', () => {
  test.each(['__proto__', 'prototype', 'constructor'])(
    'serialize rejects %s key',
    (forbidden) => {
      expect(() => {
        SuperJSON.serialize({ [forbidden]: 1 });
      }).toThrow(/prototype pollution/i);
    }
  );

  test('deserialize rejects __proto__ in referential equality paths', () => {
    expect(() => {
      SuperJSON.parse(
        JSON.stringify({
          json: { myValue: 1337 },
          meta: {
            referentialEqualities: {
              myValue: ['__proto__.x'],
            },
          },
        })
      );
    }).toThrow(/__proto__/);
  });
});

describe('Custom class registration', () => {
  test('registered class round-trips with methods', () => {
    const sj = new SuperJSON();

    class Pet {
      constructor(public name: string) {}
      speak() {
        return `${this.name} says hi`;
      }
    }
    sj.registerClass(Pet);

    const input = { pet: new Pet('Rex') };
    const output: any = sj.deserialize(sj.serialize(input));
    expect(output.pet).toBeInstanceOf(Pet);
    expect(output.pet.speak()).toBe('Rex says hi');
  });

  test('nested registered classes', () => {
    const sj = new SuperJSON();

    class Inner {
      constructor(public val: number) {}
      double() { return this.val * 2; }
    }

    class Outer {
      constructor(public inner: Inner) {}
    }

    sj.registerClass(Inner);
    sj.registerClass(Outer);

    const input = new Outer(new Inner(21));
    const output: any = sj.deserialize(sj.serialize(input));
    expect(output).toBeInstanceOf(Outer);
    expect(output.inner).toBeInstanceOf(Inner);
    expect(output.inner.double()).toBe(42);
  });
});

describe('Custom transformers', () => {
  test('custom transformer round-trip', () => {
    const sj = new SuperJSON();

    class Money {
      constructor(public amount: number, public currency: string) {}
    }

    sj.registerCustom<Money, string>(
      {
        isApplicable: (v): v is Money => v instanceof Money,
        serialize: (v) => `${v.amount}:${v.currency}`,
        deserialize: (v) => {
          const [amount, currency] = v.split(':');
          return new Money(parseFloat(amount), currency);
        },
      },
      'money'
    );

    const input = { price: new Money(9.99, 'USD') };
    const output: any = sj.deserialize(sj.serialize(input));
    expect(output.price).toBeInstanceOf(Money);
    expect(output.price.amount).toBe(9.99);
    expect(output.price.currency).toBe('USD');
  });
});

describe('Stringify and parse', () => {
  test('stringify produces valid JSON', () => {
    const input = { date: new Date(), set: new Set([1, 2]) };
    const stringified = SuperJSON.stringify(input);
    expect(() => JSON.parse(stringified)).not.toThrow();
  });

  test('parse restores original types', () => {
    const input = { date: new Date(2024, 0, 1), set: new Set([1, 2]) };
    const output: any = SuperJSON.parse(SuperJSON.stringify(input));
    expect(output.date).toBeInstanceOf(Date);
    expect(output.set).toBeInstanceOf(Set);
  });
});

describe('Edge cases', () => {
  test('index out of bounds throws for invalid Map paths', () => {
    const obj = { id: 5 };
    const highscores = new Map([[obj, 5000]]);
    const res = SuperJSON.serialize({ highscores, topScorer: obj } as any);
    (res.meta!.referentialEqualities as any).topScorer = ['highscores.99999.0'];
    expect(() => SuperJSON.deserialize(res)).toThrow('index out of bounds');
  });

  test('instances are independent', () => {
    class Car {}
    const s1 = new SuperJSON();
    s1.registerClass(Car);

    const s2 = new SuperJSON();

    const value = { car: new Car() };
    const res1 = s1.serialize(value);
    expect(res1.meta?.values).toEqual({ car: [['class', 'Car']] });

    const res2 = s2.serialize(value);
    expect(res2.json).toEqual(value);
  });

  test('no unnecessary meta for plain objects', () => {
    const input: unknown[] = [];
    const out = SuperJSON.serialize(input);
    expect(out).not.toHaveProperty('meta');
    expect(SuperJSON.deserialize(out)).toEqual(input);
  });

  test('object without prototype (Object.create(null))', () => {
    const input: Record<string, unknown> = Object.create(null);
    input.date = new Date();
    const parsed: any = SuperJSON.parse(SuperJSON.stringify(input));
    expect(parsed.date).toBeInstanceOf(Date);
  });
});

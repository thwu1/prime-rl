
import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { RingBuffer, type OverflowPolicy } from './ring-buffer.js';

// --- Model ---

interface Model {
  items: number[];
  capacity: number;
  policy: OverflowPolicy;
}

type RB = RingBuffer<number>;

// --- Command classes ---

class PushCommand implements fc.Command<Model, RB> {
  constructor(readonly value: number) {}
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    const result = r.push(this.value);
    if (m.items.length < m.capacity) {
      expect(result).toBe(true);
      m.items.push(this.value);
    } else {
      switch (m.policy) {
        case 'reject':
        case 'drop-newest':
          expect(result).toBe(false);
          break;
        case 'drop-oldest':
          expect(result).toBe(true);
          m.items.shift();
          m.items.push(this.value);
          break;
      }
    }
    expect(r.size).toBe(m.items.length);
  }
  toString() {
    return `push(${this.value})`;
  }
}

class PopCommand implements fc.Command<Model, RB> {
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    const result = r.pop();
    if (m.items.length === 0) {
      expect(result).toBeUndefined();
    } else {
      expect(result).toBe(m.items.shift());
    }
    expect(r.size).toBe(m.items.length);
  }
  toString() {
    return 'pop()';
  }
}

class PeekCommand implements fc.Command<Model, RB> {
  constructor(readonly offset: number) {}
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    const result = r.peek(this.offset);
    if (this.offset < 0 || this.offset >= m.items.length) {
      expect(result).toBeUndefined();
    } else {
      expect(result).toBe(m.items[this.offset]);
    }
  }
  toString() {
    return `peek(${this.offset})`;
  }
}

class PushManyCommand implements fc.Command<Model, RB> {
  constructor(readonly values: number[]) {}
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    const count = r.pushMany(this.values);
    let expectedAccepted = 0;
    for (const v of this.values) {
      if (m.items.length < m.capacity) {
        m.items.push(v);
        expectedAccepted++;
      } else {
        switch (m.policy) {
          case 'reject':
          case 'drop-newest':
            // rejected
            break;
          case 'drop-oldest':
            m.items.shift();
            m.items.push(v);
            expectedAccepted++;
            break;
        }
      }
    }
    expect(count).toBe(expectedAccepted);
    expect(r.size).toBe(m.items.length);
  }
  toString() {
    return `pushMany([${this.values.join(',')}])`;
  }
}

class ToArrayCommand implements fc.Command<Model, RB> {
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    expect(r.toArray()).toEqual([...m.items]);
  }
  toString() {
    return 'toArray()';
  }
}

class ClearCommand implements fc.Command<Model, RB> {
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    r.clear();
    m.items = [];
    expect(r.size).toBe(0);
    expect(r.isEmpty).toBe(true);
  }
  toString() {
    return 'clear()';
  }
}

class SetPolicyCommand implements fc.Command<Model, RB> {
  constructor(readonly newPolicy: OverflowPolicy) {}
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    r.setPolicy(this.newPolicy);
    m.policy = this.newPolicy;
    expect(r.policy).toBe(this.newPolicy);
  }
  toString() {
    return `setPolicy("${this.newPolicy}")`;
  }
}

class CheckInvariantsCommand implements fc.Command<Model, RB> {
  check(_m: Readonly<Model>) {
    return true;
  }
  run(m: Model, r: RB): void {
    expect(r.size).toBe(m.items.length);
    expect(r.isEmpty).toBe(m.items.length === 0);
    expect(r.isFull).toBe(m.items.length === m.capacity);
    expect(r.capacity).toBe(m.capacity);
    expect(r.policy).toBe(m.policy);
  }
  toString() {
    return 'checkInvariants()';
  }
}

// --- Test suite ---

describe('RingBuffer model-based property tests', () => {
  const policyArb = fc.constantFrom<OverflowPolicy>(
    'drop-oldest',
    'drop-newest',
    'reject',
  );

  const allCommands = [
    fc.integer({ min: -50, max: 50 }).map((v) => new PushCommand(v)),
    fc.constant(new PopCommand()),
    fc
      .integer({ min: -1, max: 10 })
      .map((offset) => new PeekCommand(offset)),
    fc
      .array(fc.integer({ min: -50, max: 50 }), {
        minLength: 1,
        maxLength: 5,
      })
      .map((items) => new PushManyCommand(items)),
    fc.constant(new ToArrayCommand()),
    fc.constant(new ClearCommand()),
    policyArb.map((p) => new SetPolicyCommand(p)),
    fc.constant(new CheckInvariantsCommand()),
  ];

  it('should maintain model-real consistency across all operation sequences', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 8 }),
        policyArb,
        fc.commands(allCommands, { size: '+1' }),
        (capacity, policy, cmds) => {
          const model: Model = { items: [], capacity, policy };
          const real = new RingBuffer<number>({ capacity, policy });
          fc.modelRun(() => ({ model, real }), cmds);
        },
      ),
      { numRuns: 500, seed: 42 },
    );
  });

  it('should maintain consistency with drop-oldest under overflow pressure', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 4 }),
        fc.commands(
          [
            fc.integer({ min: 0, max: 20 }).map((v) => new PushCommand(v)),
            fc.constant(new PopCommand()),
            fc
              .integer({ min: 0, max: 5 })
              .map((o) => new PeekCommand(o)),
            fc.constant(new ToArrayCommand()),
            fc.constant(new CheckInvariantsCommand()),
          ],
          { size: '+1' },
        ),
        (capacity, cmds) => {
          const model: Model = {
            items: [],
            capacity,
            policy: 'drop-oldest',
          };
          const real = new RingBuffer<number>({
            capacity,
            policy: 'drop-oldest',
          });
          fc.modelRun(() => ({ model, real }), cmds);
        },
      ),
      { numRuns: 500, seed: 1337 },
    );
  });
});

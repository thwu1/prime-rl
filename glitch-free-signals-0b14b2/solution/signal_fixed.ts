import {
  EqualFn,
  defaultEqual,
  ProducerNode,
  recordRead,
  getActiveConsumer,
  incrementEpoch,
  producerNotifyConsumers,
} from './graph';

export interface WritableSignal<T> {
  (): T;
  set(value: T): void;
  update(fn: (current: T) => T): void;
}

export function signal<T>(
  initialValue: T,
  options?: { equal?: EqualFn<T> }
): WritableSignal<T> {
  const equal: EqualFn<T> = options?.equal ?? defaultEqual;
  let value: T = initialValue;

  const node: ProducerNode = {
    version: 0,
    lastCleanEpoch: 0,
    subscribers: new Set(),
    ensureUpToDate() {
      // Signals hold their value directly — always up-to-date.
    },
  };

  const s = (() => {
    recordRead(node);
    return value;
  }) as WritableSignal<T>;

  s.set = (newValue: T) => {
    // Write guard: prevent signal writes inside computed context
    const consumer = getActiveConsumer();
    if (consumer !== null && !consumer.allowSignalWrites) {
      throw new Error('Writing to signals is not allowed in a computed');
    }

    if (!equal(value, newValue)) {
      value = newValue;
      node.version++;
      incrementEpoch();
      producerNotifyConsumers(node);
    }
  };

  s.update = (fn: (v: T) => T) => {
    s.set(fn(value));
  };

  return s;
}

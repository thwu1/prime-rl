import { EqualFn, defaultEqual, ProducerNode, recordRead, producerChanged } from './graph';

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
    subscribers: new Set(),
  };

  const s = (() => {
    recordRead(node);
    return value;
  }) as WritableSignal<T>;

  s.set = (newValue: T) => {
    if (!equal(value, newValue)) {
      value = newValue;
      producerChanged(node);
    }
  };

  s.update = (fn: (v: T) => T) => {
    s.set(fn(value));
  };

  return s;
}

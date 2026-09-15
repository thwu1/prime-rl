import {
  EqualFn,
  defaultEqual,
  ProducerNode,
  ConsumerNode,
  recordRead,
  producerChanged,
  setActiveConsumer,
} from './graph';

export interface ReadonlySignal<T> {
  (): T;
}

const UNSET = Symbol('UNSET');

export function computed<T>(
  computation: () => T,
  options?: { equal?: EqualFn<T> }
): ReadonlySignal<T> {
  const equal: EqualFn<T> = options?.equal ?? defaultEqual;
  let value: T | typeof UNSET = UNSET;

  const producerNode: ProducerNode = {
    version: 0,
    subscribers: new Set(),
  };

  const consumerNode: ConsumerNode = {
    producers: new Set(),
    onNotify() {
      evaluate();
      producerChanged(producerNode);
    },
  };

  function evaluate(): void {
    const prev = setActiveConsumer(consumerNode);
    try {
      const newValue = computation();
      value = newValue;
    } finally {
      setActiveConsumer(prev);
    }
  }

  const c = (() => {
    if (value === UNSET) {
      evaluate();
    }
    recordRead(producerNode);
    return value as T;
  }) as ReadonlySignal<T>;

  return c;
}

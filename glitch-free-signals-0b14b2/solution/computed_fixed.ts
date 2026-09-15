import {
  EqualFn,
  defaultEqual,
  ProducerNode,
  ConsumerNode,
  recordRead,
  producerNotifyConsumers,
  setActiveConsumer,
  consumerPollProducersForChange,
  cleanupConsumerDeps,
  getEpoch,
} from './graph';

export interface ReadonlySignal<T> {
  (): T;
}

const UNSET = Symbol('UNSET');
const COMPUTING = Symbol('COMPUTING');

export function computed<T>(
  computation: () => T,
  options?: { equal?: EqualFn<T> }
): ReadonlySignal<T> {
  const equal: EqualFn<T> = options?.equal ?? defaultEqual;
  let value: T | symbol = UNSET;

  const producerNode: ProducerNode = {
    version: 0,
    lastCleanEpoch: -1,
    subscribers: new Set(),
    ensureUpToDate() {
      updateIfNeeded();
    },
  };

  const consumerNode: ConsumerNode = {
    deps: new Map(),
    dirty: true,
    allowSignalWrites: false,
    onMarkedDirty() {
      // Propagate dirty to our downstream consumers
      producerNotifyConsumers(producerNode);
    },
  };

  function updateIfNeeded(): void {
    // Fast path: not dirty and epoch hasn't changed since last clean check
    if (!consumerNode.dirty && producerNode.lastCleanEpoch === getEpoch()) {
      return;
    }

    // If we have a computed value, check if any producer actually changed
    if (value !== UNSET && value !== COMPUTING) {
      if (!consumerPollProducersForChange(consumerNode)) {
        // No dependencies changed — mark clean without recomputing
        consumerNode.dirty = false;
        producerNode.lastCleanEpoch = getEpoch();
        return;
      }
    }

    // Need to recompute
    evaluate();
  }

  function evaluate(): void {
    // Cycle detection: if we're already computing, we have a cycle
    if (value === COMPUTING) {
      throw new Error('Cycle detected in computed signal');
    }

    const oldValue = value;
    value = COMPUTING;

    // Clean up old dependencies before re-evaluating (dynamic dep tracking)
    cleanupConsumerDeps(consumerNode);

    const prev = setActiveConsumer(consumerNode);
    let newValue: T;
    try {
      newValue = computation();
    } catch (err) {
      // On error, restore previous value (or UNSET if no previous)
      value = oldValue === COMPUTING ? UNSET : oldValue;
      throw err;
    } finally {
      setActiveConsumer(prev);
    }

    // Equality cutoff: if the new value equals the old, don't increment version
    if (oldValue !== UNSET && oldValue !== COMPUTING && equal(oldValue as T, newValue)) {
      value = oldValue;
    } else {
      value = newValue;
      producerNode.version++;
    }

    consumerNode.dirty = false;
    producerNode.lastCleanEpoch = getEpoch();
  }

  const c = (() => {
    // Pull-based: ensure we're up-to-date before returning
    updateIfNeeded();
    recordRead(producerNode);
    return value as T;
  }) as ReadonlySignal<T>;

  return c;
}

/**
 * Core reactive graph tracking — fixed implementation.
 * Uses epoch-based versioning and pull-based lazy evaluation for glitch-free
 * reactivity. Supports dynamic dependency cleanup and write guards.
 *
 */

export type EqualFn<T> = (a: T, b: T) => boolean;

export function defaultEqual<T>(a: T, b: T): boolean {
  return Object.is(a, b);
}

let activeConsumer: ConsumerNode | null = null;
let epoch = 0;

export interface ProducerNode {
  version: number;
  lastCleanEpoch: number;
  subscribers: Set<ConsumerNode>;
  /** Ensure this producer's value/version is up-to-date (triggers lazy recompute for computeds). */
  ensureUpToDate(): void;
}

export interface ConsumerNode {
  /** Dependencies: maps each producer to the version seen when last read. */
  deps: Map<ProducerNode, number>;
  dirty: boolean;
  /** Whether signal writes are allowed when this consumer is active (false for computeds). */
  allowSignalWrites: boolean;
  /** Called when this consumer is marked dirty via push notification. */
  onMarkedDirty(): void;
}

export function getEpoch(): number {
  return epoch;
}

export function incrementEpoch(): void {
  epoch++;
}

export function setActiveConsumer(consumer: ConsumerNode | null): ConsumerNode | null {
  const prev = activeConsumer;
  activeConsumer = consumer;
  return prev;
}

export function getActiveConsumer(): ConsumerNode | null {
  return activeConsumer;
}

/**
 * Record that the active consumer reads the given producer.
 * Tracks the dependency and the producer's current version.
 */
export function recordRead(producer: ProducerNode): void {
  if (activeConsumer !== null) {
    activeConsumer.deps.set(producer, producer.version);
    producer.subscribers.add(activeConsumer);
  }
}

/**
 * Mark all live consumers of this producer as dirty (push notification).
 * Does NOT eagerly recompute — consumers pull new values lazily on read.
 */
export function producerNotifyConsumers(producer: ProducerNode): void {
  for (const consumer of [...producer.subscribers]) {
    if (!consumer.dirty) {
      consumer.dirty = true;
      consumer.onMarkedDirty();
    }
  }
}

/**
 * Check whether any of this consumer's producer dependencies have changed
 * since they were last read. Triggers lazy evaluation on computed producers.
 */
export function consumerPollProducersForChange(consumer: ConsumerNode): boolean {
  for (const [producer, seenVersion] of consumer.deps) {
    if (seenVersion !== producer.version) {
      return true;
    }
    // The producer might itself be stale — force it to update.
    producer.ensureUpToDate();
    if (seenVersion !== producer.version) {
      return true;
    }
  }
  return false;
}

/**
 * Remove this consumer from all its producers' subscriber sets
 * and clear the dependency map. Used before re-evaluation to rebuild
 * the dependency set fresh (enabling dynamic dependency tracking).
 */
export function cleanupConsumerDeps(consumer: ConsumerNode): void {
  for (const [producer] of consumer.deps) {
    producer.subscribers.delete(consumer);
  }
  consumer.deps.clear();
}

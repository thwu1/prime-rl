/**
 * Core reactive graph tracking.
 * Manages dependency relationships between producers (signals, computeds)
 * and consumers (computeds, effects).
 *
 */

export type EqualFn<T> = (a: T, b: T) => boolean;

export function defaultEqual<T>(a: T, b: T): boolean {
  return Object.is(a, b);
}

let activeConsumer: ConsumerNode | null = null;

export interface ProducerNode {
  version: number;
  subscribers: Set<ConsumerNode>;
}

export interface ConsumerNode {
  producers: Set<ProducerNode>;
  onNotify(): void;
}

export function setActiveConsumer(consumer: ConsumerNode | null): ConsumerNode | null {
  const prev = activeConsumer;
  activeConsumer = consumer;
  return prev;
}

export function getActiveConsumer(): ConsumerNode | null {
  return activeConsumer;
}

export function recordRead(producer: ProducerNode): void {
  if (activeConsumer !== null) {
    activeConsumer.producers.add(producer);
    producer.subscribers.add(activeConsumer);
  }
}

export function producerChanged(producer: ProducerNode): void {
  producer.version++;
  const subs = [...producer.subscribers];
  for (const consumer of subs) {
    consumer.onNotify();
  }
}

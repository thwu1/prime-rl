import {
  ConsumerNode,
  setActiveConsumer,
  consumerPollProducersForChange,
  cleanupConsumerDeps,
} from './graph';

export type CleanupFn = () => void;
export type EffectFn = (onCleanup: (fn: CleanupFn) => void) => void;

export interface EffectRef {
  destroy(): void;
}

interface EffectNode {
  run(): void;
  destroyed: boolean;
  version: number;
}

// Use a Set for automatic deduplication
const pendingEffects = new Set<EffectNode>();

export function effect(fn: EffectFn): EffectRef {
  let cleanupFn: CleanupFn | null = null;

  const onCleanup = (registeredFn: CleanupFn) => {
    cleanupFn = registeredFn;
  };

  const consumerNode: ConsumerNode = {
    deps: new Map(),
    dirty: true,
    allowSignalWrites: true,
    onMarkedDirty() {
      if (!node.destroyed) {
        pendingEffects.add(node);
      }
    },
  };

  const node: EffectNode = {
    destroyed: false,
    version: 0,
    run() {
      if (node.destroyed) return;

      consumerNode.dirty = false;

      // Pull-based verification: check if producers actually changed
      if (node.version > 0 && !consumerPollProducersForChange(consumerNode)) {
        return;
      }
      node.version++;

      // Run cleanup from previous execution
      if (cleanupFn) {
        cleanupFn();
        cleanupFn = null;
      }

      // Clean up old dependencies before re-evaluation (dynamic dep tracking)
      cleanupConsumerDeps(consumerNode);

      const prev = setActiveConsumer(consumerNode);
      try {
        fn(onCleanup);
      } finally {
        setActiveConsumer(prev);
      }
    },
  };

  // Schedule initial run
  pendingEffects.add(node);

  return {
    destroy() {
      node.destroyed = true;
      pendingEffects.delete(node);
      // Clean up subscriptions so producers don't hold references
      cleanupConsumerDeps(consumerNode);
      // Run final cleanup if registered
      if (cleanupFn) {
        cleanupFn();
        cleanupFn = null;
      }
    },
  };
}

export function flushEffects(): void {
  while (pendingEffects.size > 0) {
    const batch = [...pendingEffects];
    pendingEffects.clear();
    for (const node of batch) {
      if (!node.destroyed) {
        node.run();
      }
    }
  }
}

import { ConsumerNode, setActiveConsumer } from './graph';

export type CleanupFn = () => void;
export type EffectFn = (onCleanup: (fn: CleanupFn) => void) => void;

export interface EffectRef {
  destroy(): void;
}

interface EffectNode {
  run(): void;
  destroyed: boolean;
}

const pendingEffects: EffectNode[] = [];

export function effect(fn: EffectFn): EffectRef {
  const onCleanup = (_cleanupFn: CleanupFn) => {
    // cleanup not implemented
  };

  const consumerNode: ConsumerNode = {
    producers: new Set(),
    onNotify() {
      if (!node.destroyed) {
        pendingEffects.push(node);
      }
    },
  };

  const node: EffectNode = {
    destroyed: false,
    run() {
      if (node.destroyed) return;
      const prev = setActiveConsumer(consumerNode);
      try {
        fn(onCleanup);
      } finally {
        setActiveConsumer(prev);
      }
    },
  };

  pendingEffects.push(node);

  return {
    destroy() {
      node.destroyed = true;
    },
  };
}

export function flushEffects(): void {
  while (pendingEffects.length > 0) {
    const batch = pendingEffects.splice(0);
    for (const node of batch) {
      if (!node.destroyed) {
        node.run();
      }
    }
  }
}

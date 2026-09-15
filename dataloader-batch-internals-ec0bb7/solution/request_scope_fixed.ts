
import DataLoader, { BatchLoadFn, Options } from './dataloader';
import { LRUCacheMap } from './lru-cache';
import { BatchCoalescer } from './batch-coalescer';

export interface RequestScopeOptions {
  maxCacheSize?: number;
}

export class RequestScope {
  private _coalescer: BatchCoalescer;
  private _scheduler: (callback: () => void) => void;
  private _loaders: DataLoader<any, any, any>[] = [];
  private _maxCacheSize: number;
  private _disposed: boolean = false;

  constructor(options?: RequestScopeOptions) {
    this._coalescer = new BatchCoalescer();
    // FIX: Create ONE shared scheduler from the coalescer for all loaders.
    this._scheduler = this._coalescer.createScheduler();
    this._maxCacheSize = options?.maxCacheSize ?? 100;
  }

  createLoader<K, V, C = K>(
    name: string,
    batchFn: BatchLoadFn<K, V>,
    loaderOptions?: Pick<Options<K, V, C>, 'cacheKeyFn' | 'maxBatchSize'>,
  ): DataLoader<K, V, C> {
    if (this._disposed) {
      throw new Error('Cannot create loader on a disposed RequestScope');
    }

    const loader = new DataLoader<K, V, C>(batchFn, {
      ...loaderOptions,
      name,
      // FIX 1: Route dispatch through the coalescer's shared scheduler.
      batchScheduleFn: this._scheduler,
      // FIX 2: Use bounded LRU cache instead of default unbounded Map.
      cacheMap: new LRUCacheMap<C, Promise<V>>(this._maxCacheSize) as any,
    });

    this._loaders.push(loader);
    return loader;
  }

  dispose(): void {
    // FIX 3: Clear all loader caches before releasing references,
    // so externally-held loader references observe empty caches.
    for (const loader of this._loaders) {
      loader.clearAll();
    }
    this._disposed = true;
    this._loaders = [];
  }

  get disposed(): boolean {
    return this._disposed;
  }
}

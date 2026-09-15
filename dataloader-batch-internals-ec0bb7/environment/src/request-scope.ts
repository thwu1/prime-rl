
import DataLoader, { BatchLoadFn, Options } from './dataloader';
import { LRUCacheMap } from './lru-cache';
import { BatchCoalescer } from './batch-coalescer';

export interface RequestScopeOptions {
  maxCacheSize?: number;
}

export class RequestScope {
  private _coalescer: BatchCoalescer;
  private _loaders: DataLoader<any, any, any>[] = [];
  private _maxCacheSize: number;
  private _disposed: boolean = false;

  constructor(options?: RequestScopeOptions) {
    this._coalescer = new BatchCoalescer();
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
    });

    this._loaders.push(loader);
    return loader;
  }

  dispose(): void {
    this._disposed = true;
    this._loaders = [];
  }

  get disposed(): boolean {
    return this._disposed;
  }
}

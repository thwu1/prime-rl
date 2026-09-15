
export type BatchLoadFn<K, V> = (
  keys: ReadonlyArray<K>,
) => PromiseLike<ArrayLike<V | Error>>;

export interface CacheMap<K, V> {
  get(key: K): V | void;
  set(key: K, value: V): any;
  delete(key: K): any;
  clear(): any;
}

export interface Options<K, V, C = K> {
  batch?: boolean;
  maxBatchSize?: number;
  batchScheduleFn?: (callback: () => void) => void;
  cache?: boolean;
  cacheKeyFn?: (key: K) => C;
  cacheMap?: CacheMap<C, Promise<V>> | null;
  name?: string | null;
}

interface Batch<K, V> {
  hasDispatched: boolean;
  keys: K[];
  callbacks: Array<{
    resolve: (value: V) => void;
    reject: (error: Error) => void;
  }>;
  cacheHits?: Array<() => void>;
}

// FIX 1: Use Promise.resolve().then(() => process.nextTick(fn)) instead of
// process.nextTick(fn) directly. This ensures the dispatch callback runs
// AFTER all pending microtask-queued promise continuations complete.
let resolvedPromise: Promise<void> | undefined;

const enqueuePostPromiseJob: (fn: () => void) => void =
  typeof process === 'object' && typeof process.nextTick === 'function'
    ? function (fn: () => void) {
        if (!resolvedPromise) {
          resolvedPromise = Promise.resolve();
        }
        resolvedPromise.then(() => {
          process.nextTick(fn);
        });
      }
    : typeof setImmediate === 'function'
      ? function (fn: () => void) {
          setImmediate(fn);
        }
      : function (fn: () => void) {
          setTimeout(fn);
        };

class DataLoader<K, V, C = K> {
  _batchLoadFn: BatchLoadFn<K, V>;
  _maxBatchSize: number;
  _batchScheduleFn: (callback: () => void) => void;
  _cacheKeyFn: (key: K) => C;
  _cacheMap: CacheMap<C, Promise<V>> | null;
  _batch: Batch<K, V> | null;
  name: string | null;

  constructor(batchLoadFn: BatchLoadFn<K, V>, options?: Options<K, V, C>) {
    if (typeof batchLoadFn !== 'function') {
      throw new TypeError(
        'DataLoader must be constructed with a function which accepts ' +
          `Array<key> and returns Promise<Array<value>>, but got: ${batchLoadFn}.`,
      );
    }
    this._batchLoadFn = batchLoadFn;
    this._maxBatchSize = getValidMaxBatchSize(options);
    this._batchScheduleFn = getValidBatchScheduleFn(options);
    this._cacheKeyFn = getValidCacheKeyFn(options);
    this._cacheMap = getValidCacheMap(options);
    this._batch = null;
    this.name = getValidName(options);
  }

  load(key: K): Promise<V> {
    if (key === null || key === undefined) {
      throw new TypeError(
        'The loader.load() function must be called with a value, ' +
          `but got: ${String(key)}.`,
      );
    }

    const batch = getCurrentBatch(this);
    const cacheMap = this._cacheMap;

    // FIX 2: Cache-hit coalescing. Instead of returning the cached promise
    // directly, wrap resolution in a new Promise deferred via batch.cacheHits.
    if (cacheMap) {
      const cacheKey = this._cacheKeyFn(key);
      const cachedPromise = cacheMap.get(cacheKey);
      if (cachedPromise) {
        const cacheHits = batch.cacheHits || (batch.cacheHits = []);
        return new Promise<V>((resolve) => {
          cacheHits.push(() => {
            resolve(cachedPromise);
          });
        });
      }
    }

    batch.keys.push(key);
    const promise = new Promise<V>((resolve, reject) => {
      batch.callbacks.push({ resolve, reject });
    });

    if (cacheMap) {
      const cacheKey = this._cacheKeyFn(key);
      cacheMap.set(cacheKey, promise);
    }

    return promise;
  }

  loadMany(keys: ReadonlyArray<K>): Promise<Array<V | Error>> {
    if (!isArrayLike(keys)) {
      throw new TypeError(
        'The loader.loadMany() function must be called with Array<key> ' +
          `but got: ${(keys as any)}.`,
      );
    }
    const loadPromises: Array<Promise<V | Error>> = [];
    for (let i = 0; i < keys.length; i++) {
      loadPromises.push(this.load(keys[i]).catch((error: Error) => error));
    }
    return Promise.all(loadPromises);
  }

  clear(key: K): this {
    const cacheMap = this._cacheMap;
    if (cacheMap) {
      const cacheKey = this._cacheKeyFn(key);
      cacheMap.delete(cacheKey);
    }
    return this;
  }

  clearAll(): this {
    const cacheMap = this._cacheMap;
    if (cacheMap) {
      cacheMap.clear();
    }
    return this;
  }

  prime(key: K, value: V | Promise<V> | Error): this {
    const cacheMap = this._cacheMap;
    if (cacheMap) {
      const cacheKey = this._cacheKeyFn(key);
      if (cacheMap.get(cacheKey) === undefined) {
        let promise: Promise<V>;
        if (value instanceof Error) {
          promise = Promise.reject(value);
          // FIX 6: Suppress unhandled rejection warning
          promise.catch(() => {});
        } else {
          promise = Promise.resolve(value as V);
        }
        cacheMap.set(cacheKey, promise);
      }
    }
    return this;
  }
}

function getCurrentBatch<K, V>(loader: DataLoader<K, V, any>): Batch<K, V> {
  const existingBatch = loader._batch;
  if (
    existingBatch !== null &&
    !existingBatch.hasDispatched &&
    // FIX 3: Use strict less-than (not <=) so batch contains at most
    // maxBatchSize keys.
    existingBatch.keys.length < loader._maxBatchSize
  ) {
    return existingBatch;
  }

  const newBatch: Batch<K, V> = {
    hasDispatched: false,
    keys: [],
    callbacks: [],
  };
  loader._batch = newBatch;

  loader._batchScheduleFn(() => {
    dispatchBatch(loader, newBatch);
  });

  return newBatch;
}

function dispatchBatch<K, V>(
  loader: DataLoader<K, V, any>,
  batch: Batch<K, V>,
): void {
  batch.hasDispatched = true;

  if (batch.keys.length === 0) {
    resolveCacheHits(batch);
    return;
  }

  let batchPromise: PromiseLike<ArrayLike<V | Error>>;
  try {
    batchPromise = loader._batchLoadFn(batch.keys);
  } catch (e) {
    return failedDispatch(
      loader,
      batch,
      new TypeError(
        'DataLoader must be constructed with a function which accepts ' +
          'Array<key> and returns Promise<Array<value>>, but the function ' +
          `errored synchronously: ${String(e)}.`,
      ),
    );
  }

  if (!batchPromise || typeof batchPromise.then !== 'function') {
    return failedDispatch(
      loader,
      batch,
      new TypeError(
        'DataLoader must be constructed with a function which accepts ' +
          'Array<key> and returns Promise<Array<value>>, but the function did ' +
          `not return a Promise: ${String(batchPromise)}.`,
      ),
    );
  }

  batchPromise
    .then((values: ArrayLike<V | Error>) => {
      if (!isArrayLike(values)) {
        throw new TypeError(
          'DataLoader must be constructed with a function which accepts ' +
            'Array<key> and returns Promise<Array<value>>, but the function did ' +
            `not return a Promise of an Array: ${String(values)}.`,
        );
      }

      // FIX 4: Array length invariant check
      if (values.length !== batch.keys.length) {
        throw new TypeError(
          'DataLoader must be constructed with a function which accepts ' +
            'Array<key> and returns Promise<Array<value>>, but the function did ' +
            'not return a Promise of an Array of the same length as the Array ' +
            'of keys.' +
            `\n\nKeys:\n${String(batch.keys)}` +
            `\n\nValues:\n${String(values)}`,
        );
      }

      resolveCacheHits(batch);

      for (let i = 0; i < batch.callbacks.length; i++) {
        const value = values[i];
        if (value instanceof Error) {
          batch.callbacks[i].reject(value);
        } else {
          batch.callbacks[i].resolve(value);
        }
      }
    })
    .then(undefined, (error: Error) => {
      failedDispatch(loader, batch, error);
    });
}

function failedDispatch<K, V>(
  loader: DataLoader<K, V, any>,
  batch: Batch<K, V>,
  error: Error,
): void {
  resolveCacheHits(batch);
  for (let i = 0; i < batch.keys.length; i++) {
    // FIX 5: Clear cache entry for each key so subsequent loads retry
    loader.clear(batch.keys[i]);
    batch.callbacks[i].reject(error);
  }
}

function resolveCacheHits<K, V>(batch: Batch<K, V>): void {
  if (batch.cacheHits) {
    for (let i = 0; i < batch.cacheHits.length; i++) {
      batch.cacheHits[i]();
    }
  }
}

function getValidMaxBatchSize(options?: Options<any, any, any>): number {
  const shouldBatch = !options || options.batch !== false;
  if (!shouldBatch) {
    return 1;
  }
  const maxBatchSize = options && options.maxBatchSize;
  if (maxBatchSize === undefined) {
    return Infinity;
  }
  if (typeof maxBatchSize !== 'number' || maxBatchSize < 1) {
    throw new TypeError(
      `maxBatchSize must be a positive number: ${maxBatchSize}`,
    );
  }
  return maxBatchSize;
}

function getValidBatchScheduleFn(
  options?: Options<any, any, any>,
): (callback: () => void) => void {
  const batchScheduleFn = options && options.batchScheduleFn;
  if (batchScheduleFn === undefined) {
    return enqueuePostPromiseJob;
  }
  if (typeof batchScheduleFn !== 'function') {
    throw new TypeError(
      `batchScheduleFn must be a function: ${batchScheduleFn}`,
    );
  }
  return batchScheduleFn;
}

function getValidCacheKeyFn<K, C>(options?: Options<K, any, C>): (key: K) => C {
  const cacheKeyFn = options && options.cacheKeyFn;
  if (cacheKeyFn === undefined) {
    return ((key: K) => key) as any;
  }
  if (typeof cacheKeyFn !== 'function') {
    throw new TypeError(`cacheKeyFn must be a function: ${cacheKeyFn}`);
  }
  return cacheKeyFn;
}

function getValidCacheMap<K, V, C>(
  options?: Options<K, V, C>,
): CacheMap<C, Promise<V>> | null {
  const shouldCache = !options || options.cache !== false;
  if (!shouldCache) {
    return null;
  }
  const cacheMap = options && options.cacheMap;
  if (cacheMap === undefined) {
    return new Map() as any;
  }
  if (cacheMap !== null) {
    const cacheFunctions = ['get', 'set', 'delete', 'clear'];
    const missingFunctions = cacheFunctions.filter(
      (fnName) => cacheMap && typeof (cacheMap as any)[fnName] !== 'function',
    );
    if (missingFunctions.length !== 0) {
      throw new TypeError(
        'Custom cacheMap missing methods: ' + missingFunctions.join(', '),
      );
    }
  }
  return cacheMap;
}

function getValidName(options?: Options<any, any, any>): string | null {
  if (options && options.name) {
    return options.name;
  }
  return null;
}

function isArrayLike(x: unknown): x is ArrayLike<unknown> {
  return (
    typeof x === 'object' &&
    x !== null &&
    typeof (x as any).length === 'number' &&
    ((x as any).length === 0 ||
      ((x as any).length > 0 &&
        Object.prototype.hasOwnProperty.call(x, (x as any).length - 1)))
  );
}

export default DataLoader;

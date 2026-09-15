
import DataLoader, { Options } from '../dataloader';
import { LRUCacheMap } from '../lru-cache';
import { BatchCoalescer } from '../batch-coalescer';
import { RequestScope } from '../request-scope';

function idLoader<K, C = K>(
  options?: Options<K, K, C>,
): [DataLoader<K, K, C>, Array<ReadonlyArray<K>>] {
  const loadCalls: Array<ReadonlyArray<K>> = [];
  const identityLoader = new DataLoader<K, K, C>((keys) => {
    loadCalls.push(keys);
    return Promise.resolve(Array.from(keys));
  }, options);
  return [identityLoader, loadCalls];
}

describe('Batch Scheduling', () => {
  it('batches multiple requests', async () => {
    const [identityLoader, loadCalls] = idLoader<number>();

    const promise1 = identityLoader.load(1);
    const promise2 = identityLoader.load(2);

    const [value1, value2] = await Promise.all([promise1, promise2]);
    expect(value1).toBe(1);
    expect(value2).toBe(2);
    expect(loadCalls).toEqual([[1, 2]]);
  });

  it('batches loads within promise chains', async () => {
    const [identityLoader, loadCalls] = idLoader<string>();

    await Promise.all([
      identityLoader.load('A'),
      Promise.resolve()
        .then(() => Promise.resolve())
        .then(() => {
          identityLoader.load('B');
          return Promise.resolve()
            .then(() => Promise.resolve())
            .then(() => {
              identityLoader.load('C');
              return Promise.resolve()
                .then(() => Promise.resolve())
                .then(() => {
                  identityLoader.load('D');
                });
            });
        }),
    ]);

    expect(loadCalls).toEqual([['A', 'B', 'C', 'D']]);
  });

  it('can call a loader from a loader', async () => {
    const deepLoadCalls: string[][] = [];
    const deepLoader = new DataLoader<string, string>((keys) => {
      deepLoadCalls.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    });

    const aLoadCalls: string[][] = [];
    const aLoader = new DataLoader<string, string>((keys) => {
      aLoadCalls.push(Array.from(keys));
      return deepLoader.loadMany(keys);
    });

    const bLoadCalls: string[][] = [];
    const bLoader = new DataLoader<string, string>((keys) => {
      bLoadCalls.push(Array.from(keys));
      return deepLoader.loadMany(keys);
    });

    const [a1, b1, a2, b2] = await Promise.all([
      aLoader.load('A1'),
      bLoader.load('B1'),
      aLoader.load('A2'),
      bLoader.load('B2'),
    ]);

    expect(a1).toBe('A1');
    expect(b1).toBe('B1');
    expect(a2).toBe('A2');
    expect(b2).toBe('B2');

    expect(aLoadCalls).toEqual([['A1', 'A2']]);
    expect(bLoadCalls).toEqual([['B1', 'B2']]);
    expect(deepLoadCalls).toEqual([['A1', 'A2', 'B1', 'B2']]);
  });
});

describe('Cache-Hit Coalescing', () => {
  it('coalesces cached and fresh loads', async () => {
    const loadCalls: number[][] = [];
    let resolveBatch: () => void = () => {};
    const loader = new DataLoader<number, number>((keys) => {
      loadCalls.push(Array.from(keys));
      return new Promise((resolve) => {
        resolveBatch = () => resolve(Array.from(keys));
      });
    });

    loader.prime(1, 1);

    const promise1 = loader.load(1);
    const promise2 = loader.load(2);

    let promise1Resolved = false;
    let promise2Resolved = false;
    promise1.then(() => {
      promise1Resolved = true;
    });
    promise2.then(() => {
      promise2Resolved = true;
    });

    await new Promise<void>((resolve) => setImmediate(resolve));

    expect(promise1Resolved).toBe(false);
    expect(promise2Resolved).toBe(false);

    resolveBatch();
    await new Promise<void>((resolve) => setImmediate(resolve));

    expect(promise1Resolved).toBe(true);
    expect(promise2Resolved).toBe(true);

    const [value1, value2] = await Promise.all([promise1, promise2]);
    expect(value1).toBe(1);
    expect(value2).toBe(2);

    expect(loadCalls).toEqual([[2]]);
  });

  it('coalesces with maxBatchSize=1', async () => {
    const loadCalls: number[][] = [];
    let resolveBatch: () => void = () => {};
    const loader = new DataLoader<number, number>(
      (keys) => {
        loadCalls.push(Array.from(keys));
        return new Promise((resolve) => {
          resolveBatch = () => resolve(Array.from(keys));
        });
      },
      { maxBatchSize: 1 },
    );

    loader.prime(1, 1);
    const promise1 = loader.load(1);
    const promise2 = loader.load(2);

    let p1Done = false;
    let p2Done = false;
    promise1.then(() => {
      p1Done = true;
    });
    promise2.then(() => {
      p2Done = true;
    });

    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(p1Done).toBe(false);
    expect(p2Done).toBe(false);

    resolveBatch();
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(p1Done).toBe(true);
    expect(p2Done).toBe(true);

    expect(loadCalls).toEqual([[2]]);
  });
});

describe('maxBatchSize Enforcement', () => {
  it('respects maxBatchSize', async () => {
    const [identityLoader, loadCalls] = idLoader<number>({ maxBatchSize: 2 });

    const promise1 = identityLoader.load(1);
    const promise2 = identityLoader.load(2);
    const promise3 = identityLoader.load(3);

    const [value1, value2, value3] = await Promise.all([
      promise1,
      promise2,
      promise3,
    ]);
    expect(value1).toBe(1);
    expect(value2).toBe(2);
    expect(value3).toBe(3);

    expect(loadCalls).toEqual([[1, 2], [3]]);
  });

  it('respects maxBatchSize with many keys', async () => {
    const [identityLoader, loadCalls] = idLoader<number>({ maxBatchSize: 3 });

    const promises = [];
    for (let i = 1; i <= 7; i++) {
      promises.push(identityLoader.load(i));
    }

    const values = await Promise.all(promises);
    expect(values).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(loadCalls).toEqual([[1, 2, 3], [4, 5, 6], [7]]);
  });

  it('coalesces identical requests across sized batches', async () => {
    const [identityLoader, loadCalls] = idLoader<number>({ maxBatchSize: 2 });

    const promise1a = identityLoader.load(1);
    const promise2 = identityLoader.load(2);
    const promise1b = identityLoader.load(1);
    const promise3 = identityLoader.load(3);

    const [value1a, value2, value1b, value3] = await Promise.all([
      promise1a,
      promise2,
      promise1b,
      promise3,
    ]);
    expect(value1a).toBe(1);
    expect(value2).toBe(2);
    expect(value1b).toBe(1);
    expect(value3).toBe(3);

    expect(loadCalls).toEqual([[1, 2], [3]]);
  });
});

describe('Array Length Invariant', () => {
  it('rejects when values length mismatch', async () => {
    const loader = new DataLoader<number, number>(async (keys) => {
      return Array.from(keys).slice(0, keys.length - 1);
    });

    const promise1 = loader.load(1);
    const promise2 = loader.load(2);

    let caughtError: Error | undefined;
    try {
      await promise1;
    } catch (error: any) {
      caughtError = error;
    }

    expect(caughtError).toBeInstanceOf(TypeError);
    expect(caughtError!.message).toContain('same length');

    await expect(promise2).rejects.toThrow(TypeError);
  });

  it('rejects when batch function returns non-array', async () => {
    const loader = new DataLoader<number, number>(async () => {
      return 'not an array' as any;
    });

    await expect(loader.load(1)).rejects.toThrow(TypeError);
  });

  it('rejects when batch function throws synchronously', async () => {
    const loader = new DataLoader<number, number>(() => {
      throw new Error('Sync throw');
    });

    await expect(loader.load(1)).rejects.toThrow('errored synchronously');
  });

  it('rejects when batch function returns non-Promise', async () => {
    const loader = new DataLoader<number, number>(
      (() => 'not a promise') as any,
    );

    await expect(loader.load(1)).rejects.toThrow('did not return a Promise');
  });
});

describe('Failed Dispatch Cache Clearing', () => {
  it('clears cache on failed dispatch', async () => {
    let callCount = 0;
    const loader = new DataLoader<string, string>(async (keys) => {
      callCount++;
      if (callCount === 1) {
        throw new Error('First batch fails');
      }
      return Array.from(keys);
    });

    await expect(loader.load('A')).rejects.toThrow('First batch fails');

    const value = await loader.load('A');
    expect(value).toBe('A');

    expect(callCount).toBe(2);
  });

  it('clears cache when batch promise rejects', async () => {
    let callCount = 0;
    const loader = new DataLoader<string, string>(async (keys) => {
      callCount++;
      if (callCount === 1) {
        return Promise.reject(new Error('Batch rejected'));
      }
      return Array.from(keys);
    });

    await expect(loader.load('X')).rejects.toThrow('Batch rejected');

    const value = await loader.load('X');
    expect(value).toBe('X');
    expect(callCount).toBe(2);
  });

  it('propagates error to all loads in failed batch', async () => {
    const loader = new DataLoader<number, number>(() =>
      Promise.reject(new Error('Batch failed')),
    );

    const p1 = loader.load(1);
    const p2 = loader.load(2);

    await expect(p1).rejects.toThrow('Batch failed');
    await expect(p2).rejects.toThrow('Batch failed');
  });
});

describe('Error Priming', () => {
  it('primes cache with Error without unhandled rejection', async () => {
    const unhandledRejections: any[] = [];
    const handler = (reason: any) => {
      unhandledRejections.push(reason);
    };
    process.on('unhandledRejection', handler);

    try {
      const [loader] = idLoader<number>();
      loader.prime(1, new Error('Error: 1'));

      await new Promise<void>((resolve) => setTimeout(resolve, 100));

      expect(
        unhandledRejections.filter(
          (r) => r instanceof Error && r.message === 'Error: 1',
        ),
      ).toHaveLength(0);

      let caughtError: Error | undefined;
      try {
        await loader.load(1);
      } catch (error: any) {
        caughtError = error;
      }
      expect(caughtError).toBeInstanceOf(Error);
      expect(caughtError!.message).toBe('Error: 1');
    } finally {
      process.removeListener('unhandledRejection', handler);
    }
  });
});

describe('LRU Cache', () => {
  it('evicts least recently used on capacity overflow', () => {
    const cache = new LRUCacheMap<string, number>(3);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.set('c', 3);

    cache.set('d', 4);

    expect(cache.get('a')).toBeUndefined();
    expect(cache.get('b')).toBe(2);
    expect(cache.get('c')).toBe(3);
    expect(cache.get('d')).toBe(4);
  });

  it('get promotes entry to MRU position', () => {
    const cache = new LRUCacheMap<string, number>(3);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.set('c', 3);

    cache.get('a');

    cache.set('d', 4);

    expect(cache.get('a')).toBe(1);
    expect(cache.get('b')).toBeUndefined();
    expect(cache.get('c')).toBe(3);
    expect(cache.get('d')).toBe(4);
  });

  it('multiple gets reorder LRU correctly', () => {
    const cache = new LRUCacheMap<string, number>(3);
    cache.set('a', 1);
    cache.set('b', 2);
    cache.set('c', 3);

    cache.get('a');
    cache.get('b');

    cache.set('d', 4);

    expect(cache.get('a')).toBe(1);
    expect(cache.get('b')).toBe(2);
    expect(cache.get('c')).toBeUndefined();
    expect(cache.get('d')).toBe(4);
  });

  it('set for existing key updates value and promotes to MRU', () => {
    const cache = new LRUCacheMap<string, number>(2);
    cache.set('a', 1);
    cache.set('b', 2);

    cache.set('a', 10);

    cache.set('c', 3);

    expect(cache.get('a')).toBe(10);
    expect(cache.get('b')).toBeUndefined();
    expect(cache.get('c')).toBe(3);
  });

  it('delete removes entry and frees capacity', () => {
    const cache = new LRUCacheMap<string, number>(2);
    cache.set('a', 1);
    cache.set('b', 2);

    cache.delete('a');

    expect(cache.get('a')).toBeUndefined();

    cache.set('c', 3);
    expect(cache.get('b')).toBe(2);
    expect(cache.get('c')).toBe(3);
  });

  it('clear removes all entries', () => {
    const cache = new LRUCacheMap<string, number>(3);
    cache.set('a', 1);
    cache.set('b', 2);

    cache.clear();

    expect(cache.get('a')).toBeUndefined();
    expect(cache.get('b')).toBeUndefined();

    cache.set('x', 10);
    cache.set('y', 20);
    cache.set('z', 30);
    expect(cache.get('x')).toBe(10);
    expect(cache.get('y')).toBe(20);
    expect(cache.get('z')).toBe(30);
  });
});

describe('DataLoader with LRU Cache', () => {
  it('uses LRU cache for deduplication', async () => {
    const loadCalls: string[][] = [];
    const loader = new DataLoader<string, string>(
      (keys) => {
        loadCalls.push(Array.from(keys));
        return Promise.resolve(Array.from(keys));
      },
      { cacheMap: new LRUCacheMap<string, Promise<string>>(10) },
    );

    const [a, b] = await Promise.all([
      loader.load('A'),
      loader.load('B'),
    ]);
    expect(a).toBe('A');
    expect(b).toBe('B');
    expect(loadCalls).toEqual([['A', 'B']]);

    const a2 = await loader.load('A');
    expect(a2).toBe('A');
    expect(loadCalls).toEqual([['A', 'B']]);
  });

  it('evicts LRU entries causing re-fetch', async () => {
    const loadCalls: string[][] = [];
    const loader = new DataLoader<string, string>(
      (keys) => {
        loadCalls.push(Array.from(keys));
        return Promise.resolve(Array.from(keys));
      },
      { cacheMap: new LRUCacheMap<string, Promise<string>>(2) },
    );

    await Promise.all([loader.load('A'), loader.load('B')]);
    expect(loadCalls).toEqual([['A', 'B']]);

    await loader.load('A');
    expect(loadCalls).toEqual([['A', 'B']]);

    await loader.load('C');
    expect(loadCalls).toEqual([['A', 'B'], ['C']]);

    await loader.load('A');
    expect(loadCalls).toEqual([['A', 'B'], ['C']]);

    await loader.load('B');
    expect(loadCalls).toEqual([['A', 'B'], ['C'], ['B']]);
  });

  it('failed dispatch with LRU cache clears entries for retry', async () => {
    let callCount = 0;
    const loader = new DataLoader<string, string>(
      async (keys) => {
        callCount++;
        if (callCount === 1) {
          throw new Error('LRU batch fails');
        }
        return Array.from(keys);
      },
      { cacheMap: new LRUCacheMap<string, Promise<string>>(10) },
    );

    await expect(loader.load('X')).rejects.toThrow('LRU batch fails');

    const value = await loader.load('X');
    expect(value).toBe('X');
    expect(callCount).toBe(2);
  });
});

describe('BatchCoalescer', () => {
  it('coalesces dispatches across multiple loaders', async () => {
    const coalescer = new BatchCoalescer();
    const scheduler = coalescer.createScheduler();

    const loadCallsA: string[][] = [];
    const loaderA = new DataLoader<string, string>((keys) => {
      loadCallsA.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    }, { batchScheduleFn: scheduler });

    const loadCallsB: string[][] = [];
    const loaderB = new DataLoader<string, string>((keys) => {
      loadCallsB.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    }, { batchScheduleFn: scheduler });

    const [a1, b1] = await Promise.all([
      loaderA.load('A1'),
      loaderB.load('B1'),
    ]);

    expect(a1).toBe('A1');
    expect(b1).toBe('B1');
    expect(loadCallsA).toEqual([['A1']]);
    expect(loadCallsB).toEqual([['B1']]);
  });

  it('coalesces loads from promise chains across loaders', async () => {
    const coalescer = new BatchCoalescer();
    const scheduler = coalescer.createScheduler();

    const loadCallsA: string[][] = [];
    const loaderA = new DataLoader<string, string>((keys) => {
      loadCallsA.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    }, { batchScheduleFn: scheduler });

    const loadCallsB: string[][] = [];
    const loaderB = new DataLoader<string, string>((keys) => {
      loadCallsB.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    }, { batchScheduleFn: scheduler });

    await Promise.all([
      loaderA.load('A1'),
      Promise.resolve()
        .then(() => {
          loaderB.load('B1');
        })
        .then(() => Promise.resolve())
        .then(() => loaderA.load('A2')),
    ]);

    expect(loadCallsA).toEqual([['A1', 'A2']]);
    expect(loadCallsB).toEqual([['B1']]);
  });

  it('handles re-entrant loads after dispatch', async () => {
    const coalescer = new BatchCoalescer();
    const scheduler = coalescer.createScheduler();

    const outerCalls: string[][] = [];
    const innerCalls: string[][] = [];

    const innerLoader = new DataLoader<string, string>((keys) => {
      innerCalls.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    }, { batchScheduleFn: scheduler });

    const outerLoader = new DataLoader<string, string>((keys) => {
      outerCalls.push(Array.from(keys));
      return innerLoader.loadMany(Array.from(keys));
    }, { batchScheduleFn: scheduler });

    const [v1, v2] = await Promise.all([
      outerLoader.load('X'),
      outerLoader.load('Y'),
    ]);

    expect(v1).toBe('X');
    expect(v2).toBe('Y');
    expect(outerCalls).toEqual([['X', 'Y']]);
    expect(innerCalls).toEqual([['X', 'Y']]);
  }, 10000);

  it('separate createScheduler calls share the same queue', async () => {
    const coalescer = new BatchCoalescer();
    const schedulerA = coalescer.createScheduler();
    const schedulerB = coalescer.createScheduler();

    const loadCallsA: string[][] = [];
    const loaderA = new DataLoader<string, string>((keys) => {
      loadCallsA.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    }, { batchScheduleFn: schedulerA });

    const loadCallsB: string[][] = [];
    const loaderB = new DataLoader<string, string>((keys) => {
      loadCallsB.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    }, { batchScheduleFn: schedulerB });

    const [a, b] = await Promise.all([
      loaderA.load('A'),
      loaderB.load('B'),
    ]);

    expect(a).toBe('A');
    expect(b).toBe('B');
    expect(loadCallsA).toEqual([['A']]);
    expect(loadCallsB).toEqual([['B']]);
  });
});

describe('RequestScope', () => {
  it('creates functional loaders', async () => {
    const scope = new RequestScope();
    const loadCalls: string[][] = [];
    const loader = scope.createLoader<string, string>('test', (keys) => {
      loadCalls.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    });

    const result = await loader.load('A');
    expect(result).toBe('A');
    expect(loadCalls).toEqual([['A']]);
  });

  it('uses bounded LRU caching via scope', async () => {
    const scope = new RequestScope({ maxCacheSize: 2 });
    const loadCalls: string[][] = [];
    const loader = scope.createLoader<string, string>('test', (keys) => {
      loadCalls.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    });

    // Load A and B, fills cache (capacity 2)
    await Promise.all([loader.load('A'), loader.load('B')]);
    expect(loadCalls).toEqual([['A', 'B']]);

    // Access A to promote it to MRU (B becomes LRU)
    await loader.load('A');
    expect(loadCalls).toEqual([['A', 'B']]);

    // Load C — should evict B (LRU), not A
    await loader.load('C');
    expect(loadCalls).toEqual([['A', 'B'], ['C']]);

    // A should still be cached (was promoted to MRU)
    await loader.load('A');
    expect(loadCalls).toEqual([['A', 'B'], ['C']]);

    // B was evicted, needs re-fetch
    await loader.load('B');
    expect(loadCalls).toEqual([['A', 'B'], ['C'], ['B']]);
  });

  it('dispose clears all loader caches', async () => {
    const scope = new RequestScope();
    const loadCalls: string[][] = [];
    const loader = scope.createLoader<string, string>('test', (keys) => {
      loadCalls.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    });

    await loader.load('A');
    expect(loadCalls).toEqual([['A']]);

    // A is cached
    await loader.load('A');
    expect(loadCalls).toEqual([['A']]);

    scope.dispose();
    expect(scope.disposed).toBe(true);

    // After dispose, cache should be cleared, A needs re-fetch
    await loader.load('A');
    expect(loadCalls).toEqual([['A'], ['A']]);
  });

  it('throws on createLoader after dispose', () => {
    const scope = new RequestScope();
    scope.dispose();
    expect(() => {
      scope.createLoader('test', async (keys) => Array.from(keys));
    }).toThrow('disposed');
  });

  it('re-entrant loads across scoped loaders', async () => {
    const scope = new RequestScope();

    const innerCalls: string[][] = [];
    const innerLoader = scope.createLoader<string, string>('inner', (keys) => {
      innerCalls.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    });

    const outerCalls: string[][] = [];
    const outerLoader = scope.createLoader<string, string>('outer', (keys) => {
      outerCalls.push(Array.from(keys));
      return innerLoader.loadMany(Array.from(keys));
    });

    const [v1, v2] = await Promise.all([
      outerLoader.load('X'),
      outerLoader.load('Y'),
    ]);

    expect(v1).toBe('X');
    expect(v2).toBe('Y');
    expect(outerCalls).toEqual([['X', 'Y']]);
    expect(innerCalls).toEqual([['X', 'Y']]);
  }, 10000);

  it('dispose across multiple loaders clears all', async () => {
    const scope = new RequestScope();

    const callsA: string[][] = [];
    const loaderA = scope.createLoader<string, string>('A', (keys) => {
      callsA.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    });

    const callsB: string[][] = [];
    const loaderB = scope.createLoader<string, string>('B', (keys) => {
      callsB.push(Array.from(keys));
      return Promise.resolve(Array.from(keys));
    });

    await loaderA.load('a1');
    await loaderB.load('b1');
    expect(callsA).toEqual([['a1']]);
    expect(callsB).toEqual([['b1']]);

    // Both cached
    await loaderA.load('a1');
    await loaderB.load('b1');
    expect(callsA).toEqual([['a1']]);
    expect(callsB).toEqual([['b1']]);

    scope.dispose();

    // After dispose, both caches are cleared
    await loaderA.load('a1');
    await loaderB.load('b1');
    expect(callsA).toEqual([['a1'], ['a1']]);
    expect(callsB).toEqual([['b1'], ['b1']]);
  });
});

describe('Core API', () => {
  it('coalesces identical requests', async () => {
    const [identityLoader, loadCalls] = idLoader<number>();

    const promise1a = identityLoader.load(1);
    const promise1b = identityLoader.load(1);

    const [value1a, value1b] = await Promise.all([promise1a, promise1b]);
    expect(value1a).toBe(1);
    expect(value1b).toBe(1);
    expect(loadCalls).toEqual([[1]]);
  });

  it('caches repeated requests across batches', async () => {
    const [identityLoader, loadCalls] = idLoader<string>();

    const [a, b] = await Promise.all([
      identityLoader.load('A'),
      identityLoader.load('B'),
    ]);
    expect(a).toBe('A');
    expect(b).toBe('B');
    expect(loadCalls).toEqual([['A', 'B']]);

    const [a2, c] = await Promise.all([
      identityLoader.load('A'),
      identityLoader.load('C'),
    ]);
    expect(a2).toBe('A');
    expect(c).toBe('C');
    expect(loadCalls).toEqual([['A', 'B'], ['C']]);
  });

  it('clears single value', async () => {
    const [identityLoader, loadCalls] = idLoader<string>();

    await identityLoader.load('A');
    expect(loadCalls).toEqual([['A']]);

    identityLoader.clear('A');
    await identityLoader.load('A');
    expect(loadCalls).toEqual([['A'], ['A']]);
  });

  it('clears all values', async () => {
    const [identityLoader, loadCalls] = idLoader<string>();

    await Promise.all([identityLoader.load('A'), identityLoader.load('B')]);
    expect(loadCalls).toEqual([['A', 'B']]);

    identityLoader.clearAll();
    await Promise.all([identityLoader.load('A'), identityLoader.load('B')]);
    expect(loadCalls).toEqual([
      ['A', 'B'],
      ['A', 'B'],
    ]);
  });

  it('allows priming the cache', async () => {
    const [identityLoader, loadCalls] = idLoader<string>();

    identityLoader.prime('A', 'A');

    const [a, b] = await Promise.all([
      identityLoader.load('A'),
      identityLoader.load('B'),
    ]);
    expect(a).toBe('A');
    expect(b).toBe('B');
    expect(loadCalls).toEqual([['B']]);
  });

  it('does not prime keys that already exist', async () => {
    const [identityLoader] = idLoader<string>();

    identityLoader.prime('A', 'X');
    const a1 = await identityLoader.load('A');
    expect(a1).toBe('X');

    identityLoader.prime('A', 'Y');
    const a2 = await identityLoader.load('A');
    expect(a2).toBe('X');
  });

  it('allows forcefully priming the cache', async () => {
    const [identityLoader, loadCalls] = idLoader<string>();

    identityLoader.prime('A', 'X');
    const a1 = await identityLoader.load('A');
    expect(a1).toBe('X');

    identityLoader.clear('A').prime('A', 'Y');
    const a2 = await identityLoader.load('A');
    expect(a2).toBe('Y');

    expect(loadCalls).toEqual([]);
  });

  it('supports loadMany', async () => {
    const [identityLoader, loadCalls] = idLoader<number>();

    const values = await identityLoader.loadMany([1, 2, 3]);
    expect(values).toEqual([1, 2, 3]);
    expect(loadCalls).toEqual([[1, 2, 3]]);
  });

  it('loadMany catches individual errors', async () => {
    const loader = new DataLoader<string, string>((keys) =>
      Promise.resolve(
        Array.from(keys).map((key) =>
          key === 'bad' ? new Error('Bad Key') : key,
        ),
      ),
    );

    const values = await loader.loadMany(['a', 'b', 'bad']);
    expect(values).toEqual(['a', 'b', new Error('Bad Key')]);
  });

  it('may disable batching', async () => {
    const [identityLoader, loadCalls] = idLoader<number>({ batch: false });

    const p1 = identityLoader.load(1);
    const p2 = identityLoader.load(2);

    const [v1, v2] = await Promise.all([p1, p2]);
    expect(v1).toBe(1);
    expect(v2).toBe(2);
    expect(loadCalls).toEqual([[1], [2]]);
  });

  it('may disable caching', async () => {
    const [identityLoader, loadCalls] = idLoader<string>({ cache: false });

    await Promise.all([identityLoader.load('A'), identityLoader.load('B')]);
    expect(loadCalls).toEqual([['A', 'B']]);

    await Promise.all([identityLoader.load('A'), identityLoader.load('C')]);
    expect(loadCalls).toEqual([
      ['A', 'B'],
      ['A', 'C'],
    ]);
  });

  it('allows custom cacheKeyFn', async () => {
    const loadCalls: Array<Array<{ id: number }>> = [];
    const loader = new DataLoader<{ id: number }, { id: number }, string>(
      (keys) => {
        loadCalls.push(Array.from(keys));
        return Promise.resolve(Array.from(keys));
      },
      { cacheKeyFn: (key) => String(key.id) },
    );

    const key1 = { id: 123 };
    const key2 = { id: 123 };

    const value1 = await loader.load(key1);
    const value2 = await loader.load(key2);

    expect(loadCalls).toEqual([[key1]]);
    expect(value1).toBe(key1);
    expect(value2).toBe(key1);
  });

  it('allows custom cacheMap', async () => {
    const stash: Record<string, any> = {};
    const customMap = {
      get(key: string) {
        return stash[key];
      },
      set(key: string, value: any) {
        stash[key] = value;
      },
      delete(key: string) {
        delete stash[key];
      },
      clear() {
        for (const k of Object.keys(stash)) delete stash[k];
      },
    };

    const [identityLoader, loadCalls] = idLoader<string>({
      cacheMap: customMap as any,
    });

    await identityLoader.load('a');
    await identityLoader.load('a');
    expect(loadCalls).toEqual([['a']]);
    expect(Object.keys(stash)).toEqual(['a']);
  });

  it('name property', () => {
    expect(
      new DataLoader<number, number>(async (keys) => Array.from(keys)).name,
    ).toBeNull();
    expect(
      new DataLoader<number, number>(async (keys) => Array.from(keys), {
        name: 'MyLoader',
      }).name,
    ).toBe('MyLoader');
  });

  it('throws on null/undefined key', () => {
    const loader = new DataLoader<any, any>(async (keys) => keys);
    expect(() => loader.load(null)).toThrow(TypeError);
    expect(() => loader.load(undefined)).toThrow(TypeError);
  });

  it('supports manual dispatch via batchScheduleFn', () => {
    let callbacks: Array<() => void> = [];
    const schedule = (callback: () => void) => {
      callbacks.push(callback);
    };
    const dispatch = () => {
      callbacks.forEach((cb) => cb());
      callbacks = [];
    };

    const [identityLoader, loadCalls] = idLoader<string>({
      batchScheduleFn: schedule,
    });

    identityLoader.load('A');
    identityLoader.load('B');
    dispatch();
    identityLoader.load('A');
    identityLoader.load('C');
    dispatch();

    expect(loadCalls).toEqual([['A', 'B'], ['C']]);
  });
});

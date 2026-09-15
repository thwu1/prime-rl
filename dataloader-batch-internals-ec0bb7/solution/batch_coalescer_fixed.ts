
/**
 * BatchCoalescer coordinates dispatch timing across multiple DataLoader
 * instances. Each DataLoader that should share dispatch timing calls
 * createScheduler() and passes the returned function as the batchScheduleFn
 * option. The coalescer ensures all registered dispatches fire together
 * after all microtask-queued promise jobs complete.
 */
export class BatchCoalescer {
  private _pendingCallbacks: Array<() => void> = [];
  private _isScheduled: boolean = false;

  /**
   * Returns a batchScheduleFn that routes dispatch callbacks through
   * this coalescer's shared scheduling queue.
   */
  createScheduler(): (callback: () => void) => void {
    return (callback: () => void) => {
      this._pendingCallbacks.push(callback);
      if (!this._isScheduled) {
        this._isScheduled = true;
        this._scheduleFlush();
      }
    };
  }

  // FIX 1: Use Promise.resolve().then(() => process.nextTick(fn)) to defer
  // flush until after all microtask-queued promise continuations complete.
  private _scheduleFlush(): void {
    Promise.resolve().then(() => {
      process.nextTick(() => {
        this._flush();
      });
    });
  }

  private _flush(): void {
    // FIX 2: Reset _isScheduled BEFORE executing callbacks so that
    // re-entrant loads (triggered during dispatch) can schedule a new flush.
    this._isScheduled = false;

    const callbacks = this._pendingCallbacks;
    this._pendingCallbacks = [];

    for (const cb of callbacks) {
      cb();
    }
  }
}

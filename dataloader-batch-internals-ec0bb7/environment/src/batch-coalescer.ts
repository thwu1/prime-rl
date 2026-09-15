
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

  private _scheduleFlush(): void {
    process.nextTick(() => {
      this._flush();
    });
  }

  private _flush(): void {
    const callbacks = this._pendingCallbacks;
    this._pendingCallbacks = [];

    for (const cb of callbacks) {
      cb();
    }

    this._isScheduled = false;
  }
}

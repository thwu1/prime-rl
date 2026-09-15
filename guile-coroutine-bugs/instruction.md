The file `/app/csp.scm` contains a Guile Scheme module `(csp)` that implements CSP-style cooperative concurrency using delimited continuations. The module has bugs in its coroutine core and is missing implementations for its channel system, `select` multiplexer, and deadlock-detecting scheduler. Fix all bugs and implement all stub procedures so the module passes the test suite.

The module must export:

**Coroutine core** (partially implemented, has bugs):
- `(spawn thunk)` — Create and register a task. Returns a task object.
- `(yield!)` — Suspend the current task, returning control to the scheduler.
- `(task-dead? t)` / `(task-result t)` — State inspection.

**Channels** (stubs — design and implement):
- `(make-channel [capacity])` — Capacity 0 or omitted: **synchronous** (unbuffered) — sender blocks until a receiver is ready and vice versa. Capacity > 0: **buffered** — sends succeed without blocking until the buffer is full.
- `(channel-send! ch value)` — Send `value` on `ch`. Blocks current task when full (buffered) or no receiver waiting (synchronous). Raises error with key `'channel-closed` if closed.
- `(channel-recv! ch)` — Receive from `ch`. Blocks when empty. Returns symbol `'channel-closed` when `ch` is closed and drained.
- `(channel-close! ch)` — Close `ch`. Unblock pending senders with `'channel-closed` error. Pending receivers get remaining buffered values then `'channel-closed`.

**Select** (stub — design and implement):
- `(select clauses)` — `clauses` is a list of `(channel . direction)` pairs where direction is `send` or `recv`. Blocks until at least one clause is ready. Returns `(channel . direction)` for the first ready clause (earliest in list wins ties).

**Scheduler** (stub — design and implement):
- `(run-scheduler tasks)` — Run tasks cooperatively until completion or deadlock. **Deadlock**: every live task is blocked on a channel operation and no progress is possible — must raise error with key `'deadlock`. Returns completed task results in completion order.

The scheduler must integrate with channel operations: when a task blocks on `channel-send!` or `channel-recv!`, its continuation is parked in the channel's wait queue. When a matching operation unblocks it, the task re-enters the run queue. `yield!` places the current task at the back of the run queue.

Verify with:
```
guile --no-auto-compile -L /app -c '
(use-modules (csp))
(let* ((ch (make-channel))
       (t1 (spawn (lambda () (channel-send! ch 42) (quote done))))
       (t2 (spawn (lambda () (channel-recv! ch)))))
  (for-each (lambda (r) (display r) (newline))
            (run-scheduler (list t1 t2))))'
```
Expected: prints `42` and `done` (completion order).

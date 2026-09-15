The file `/app/src/main/java/challenge/PriorityEvictionBuffer.java` contains a skeleton for a custom Project Reactor operator. Implement it so that all JUnit 5 tests in `/app/src/test/java/challenge/PriorityEvictionBufferTest.java` pass.

The static method `PriorityEvictionBuffer.create(Flux<T> source, int capacity, ToIntFunction<T> priorityFn, Consumer<T> onEvict)` must return a `Flux<T>` with the following behavior:

**Input validation:** Throw `NullPointerException` if `source` or `priorityFn` is null. Throw `IllegalArgumentException` if `capacity <= 0`. These must be thrown eagerly at creation time, not deferred to subscription.

**Buffering:** When the downstream subscriber has not requested elements, incoming elements are buffered internally up to `capacity`.

**Priority eviction:** When the buffer is full and a new element arrives:
- If the new element has strictly higher priority (per `priorityFn`) than the lowest-priority buffered element, evict that lowest-priority element and buffer the new one.
- If multiple buffered elements share the minimum priority, evict the one that arrived earliest.
- If the new element's priority is equal to or lower than every buffered element's priority, drop the new element instead.
- Every evicted or dropped element is passed to `onEvict` (when non-null).

**Emission order:** Elements are emitted to downstream in FIFO (arrival) order, regardless of priority.

**Reactive Streams contract:**
- Downstream `request(n)` must be honored precisely — never emit more elements than requested.
- On source error: deliver all buffered elements first, then propagate the error.
- On source completion: deliver all buffered elements first, then signal completion.
- On downstream cancellation: cancel the upstream source subscription.

**Verification:** Run `cd /app && mvn test`. All 25 tests must pass. Do not modify the test file.

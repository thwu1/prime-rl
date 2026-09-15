package challenge;

import reactor.core.publisher.Flux;
import reactor.core.publisher.FluxSink;

import java.util.*;
import java.util.function.Consumer;
import java.util.function.ToIntFunction;

/**
 * A backpressure operator that buffers elements up to a given capacity.
 * When the buffer is full and a new element arrives:
 * - If the new element has strictly higher priority than the lowest-priority
 *   buffered element, the lowest-priority element is evicted and replaced.
 * - Otherwise, the new element itself is dropped.
 * Evicted/dropped elements are reported to the onEvict callback.
 * Elements are emitted to downstream in FIFO (arrival) order.
 * Downstream backpressure (request-n) is fully honored.
 */
public class PriorityEvictionBuffer {


    /**
     * Creates a Flux that applies priority-based eviction backpressure buffering.
     *
     * @param source     the upstream Flux
     * @param capacity   maximum buffer capacity (must be > 0)
     * @param priorityFn assigns an integer priority to each element (higher = more important)
     * @param onEvict    callback invoked with each evicted or dropped element (may be null)
     * @param <T>        element type
     * @return a Flux with priority eviction backpressure
     */
    public static <T> Flux<T> create(
            Flux<T> source,
            int capacity,
            ToIntFunction<T> priorityFn,
            Consumer<T> onEvict) {

        // TODO: Add input validation (null checks, capacity > 0)

        return Flux.create(sink -> {
            LinkedList<T> buffer = new LinkedList<>();

            source.subscribe(
                value -> {
                    // TODO: Implement priority eviction buffering
                    // When buffer is not full: add element to buffer
                    // When buffer is full: compare priorities and evict if appropriate
                    // Currently just passes through without buffering or backpressure
                    sink.next(value);
                },
                error -> {
                    // TODO: Deliver buffered elements before error
                    sink.error(error);
                },
                () -> {
                    // TODO: Drain remaining buffer before completing
                    sink.complete();
                }
            );
        });
    }
}

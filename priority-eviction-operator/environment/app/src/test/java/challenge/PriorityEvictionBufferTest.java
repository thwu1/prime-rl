package challenge;

import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import reactor.test.StepVerifier;
import reactor.test.publisher.TestPublisher;

import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.ToIntFunction;

import static org.assertj.core.api.Assertions.*;


class PriorityEvictionBufferTest {

    // priority = value itself (higher value = higher priority)
    private static final ToIntFunction<Integer> VALUE_PRIORITY = i -> i;

    // constant priority (all equal)
    private static final ToIntFunction<Integer> EQUAL_PRIORITY = i -> 0;

    // --- Input validation ---

    @Test
    void rejectsNullSource() {
        assertThatNullPointerException()
            .isThrownBy(() -> PriorityEvictionBuffer.create(null, 5, VALUE_PRIORITY, v -> {}));
    }

    @Test
    void rejectsZeroCapacity() {
        assertThatIllegalArgumentException()
            .isThrownBy(() -> PriorityEvictionBuffer.create(Flux.empty(), 0, VALUE_PRIORITY, v -> {}));
    }

    @Test
    void rejectsNegativeCapacity() {
        assertThatIllegalArgumentException()
            .isThrownBy(() -> PriorityEvictionBuffer.create(Flux.empty(), -1, VALUE_PRIORITY, v -> {}));
    }

    @Test
    void rejectsNullPriorityFn() {
        assertThatNullPointerException()
            .isThrownBy(() -> PriorityEvictionBuffer.create(Flux.empty(), 5, null, v -> {}));
    }

    // --- Basic behavior ---

    @Test
    void passthroughWhenNoBackpressure() {
        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    Flux.range(1, 5),
                    10,
                    VALUE_PRIORITY,
                    null))
            .expectNext(1, 2, 3, 4, 5)
            .verifyComplete();
    }

    @Test
    void buffersWhenNoRequest() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    5,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .then(() -> source.next(10, 20, 30))
            .thenRequest(2)
            .expectNext(10, 20)
            .thenRequest(1)
            .expectNext(30)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).isEmpty();
    }

    @Test
    void emptySource() {
        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    Flux.empty(),
                    5,
                    VALUE_PRIORITY,
                    null))
            .verifyComplete();
    }

    // --- Priority eviction ---

    @Test
    void priorityEvictionWhenBufferFull() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    3,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .then(() -> source.next(5, 3, 7))
            .then(() -> source.next(10))
            .thenRequest(3)
            .expectNext(5, 7, 10)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(3);
    }

    @Test
    void dropNewWhenLowerPriority() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    3,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .then(() -> source.next(5, 8, 7))
            .then(() -> source.next(2))
            .thenRequest(3)
            .expectNext(5, 8, 7)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(2);
    }

    @Test
    void dropNewWhenEqualPriority() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        ToIntFunction<Integer> modPriority = i -> i % 10;

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    2,
                    modPriority,
                    evicted::add),
                0)
            .then(() -> source.next(15, 25))
            .then(() -> source.next(35))
            .thenRequest(2)
            .expectNext(15, 25)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(35);
    }

    @Test
    void multipleEvictions() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    3,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .then(() -> source.next(1, 2, 3))
            .then(() -> source.next(4))
            .then(() -> source.next(5))
            .then(() -> source.next(6))
            .thenRequest(3)
            .expectNext(4, 5, 6)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(1, 2, 3);
    }

    @Test
    void capacityOne() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    1,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .then(() -> source.next(5))
            .then(() -> source.next(3))
            .then(() -> source.next(10))
            .then(() -> source.next(7))
            .thenRequest(1)
            .expectNext(10)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(3, 5, 7);
    }

    // --- Ordering ---

    @Test
    void fifoOrderPreserved() {
        TestPublisher<Integer> source = TestPublisher.create();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    5,
                    VALUE_PRIORITY,
                    null),
                0)
            .then(() -> source.next(30, 10, 50, 20, 40))
            .thenRequest(5)
            .expectNext(30, 10, 50, 20, 40)
            .then(source::complete)
            .verifyComplete();
    }

    @Test
    void evictionPreservesInsertionOrder() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        ToIntFunction<Integer> evenHighPriority = i -> (i % 2 == 0) ? 100 : 1;

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    4,
                    evenHighPriority,
                    evicted::add),
                0)
            .then(() -> source.next(1, 2, 3, 4))
            .then(() -> source.next(6))
            .then(() -> source.next(8))
            .thenRequest(4)
            .expectNext(2, 4, 6, 8)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(1, 3);
    }

    // --- Lifecycle ---

    @Test
    void errorPropagation() {
        TestPublisher<Integer> source = TestPublisher.create();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    5,
                    VALUE_PRIORITY,
                    null))
            .then(() -> source.next(1))
            .expectNext(1)
            .then(() -> source.error(new IllegalStateException("boom")))
            .expectErrorMessage("boom");
    }

    @Test
    void errorAfterBufferedElements() {
        TestPublisher<Integer> source = TestPublisher.create();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    5,
                    VALUE_PRIORITY,
                    null),
                0)
            .then(() -> source.next(1, 2, 3))
            .then(() -> source.error(new IllegalStateException("boom")))
            .thenRequest(3)
            .expectNext(1, 2, 3)
            .expectErrorMessage("boom");
    }

    @Test
    void completionDrainsBuffer() {
        TestPublisher<Integer> source = TestPublisher.create();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    5,
                    VALUE_PRIORITY,
                    null),
                0)
            .then(() -> source.next(1, 2, 3))
            .then(source::complete)
            .thenRequest(3)
            .expectNext(1, 2, 3)
            .verifyComplete();
    }

    @Test
    void cancellationStopsSource() {
        TestPublisher<Integer> source = TestPublisher.create();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    5,
                    VALUE_PRIORITY,
                    null),
                0)
            .then(() -> source.next(1, 2))
            .thenRequest(1)
            .expectNext(1)
            .thenCancel()
            .verify();

        source.assertCancelled();
    }

    // --- Edge cases ---

    @Test
    void singleElement() {
        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    Flux.just(42),
                    5,
                    VALUE_PRIORITY,
                    null))
            .expectNext(42)
            .verifyComplete();
    }

    @Test
    void nullEvictCallback() {
        TestPublisher<Integer> source = TestPublisher.create();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    2,
                    VALUE_PRIORITY,
                    null),
                0)
            .then(() -> source.next(1, 2))
            .then(() -> source.next(3))
            .thenRequest(2)
            .expectNext(2, 3)
            .then(source::complete)
            .verifyComplete();
    }

    @Test
    void allSamePriorityDropsNew() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    3,
                    EQUAL_PRIORITY,
                    evicted::add),
                0)
            .then(() -> source.next(1, 2, 3))
            .then(() -> source.next(4))
            .then(() -> source.next(5))
            .thenRequest(3)
            .expectNext(1, 2, 3)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(4, 5);
    }

    // --- Complex scenarios ---

    @Test
    void stepByStepRequestAccounting() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    3,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .then(() -> source.next(1))
            .thenRequest(1)
            .expectNext(1)
            .then(() -> source.next(2, 3, 4))
            .thenRequest(1)
            .expectNext(2)
            .then(() -> source.next(5, 6))
            .thenRequest(1)
            .expectNext(4)
            .thenRequest(2)
            .expectNext(5, 6)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(3);
    }

    @Test
    void largeBurstHandling() {
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        Flux<Integer> source = Flux.range(1, 100);

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source,
                    10,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .thenRequest(10)
            .expectNext(91, 92, 93, 94, 95, 96, 97, 98, 99, 100)
            .verifyComplete();

        assertThat(evicted).hasSize(90);
    }

    @Test
    void mixedRequestAndPush() {
        TestPublisher<Integer> source = TestPublisher.create();
        List<Integer> evicted = new CopyOnWriteArrayList<>();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    2,
                    VALUE_PRIORITY,
                    evicted::add),
                0)
            .thenRequest(2)
            .then(() -> source.next(10))
            .expectNext(10)
            .then(() -> source.next(20))
            .expectNext(20)
            .then(() -> source.next(5, 15))
            .then(() -> source.next(25))
            .thenRequest(2)
            .expectNext(15, 25)
            .then(source::complete)
            .verifyComplete();

        assertThat(evicted).containsExactly(5);
    }

    @Test
    void requestBeforePush() {
        TestPublisher<Integer> source = TestPublisher.create();

        StepVerifier.create(
                PriorityEvictionBuffer.create(
                    source.flux(),
                    5,
                    VALUE_PRIORITY,
                    null),
                3)
            .then(() -> source.next(100, 200, 300))
            .expectNext(100, 200, 300)
            .then(source::complete)
            .verifyComplete();
    }
}

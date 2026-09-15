#!/usr/bin/env python3
"""Write the correct PriorityEvictionBuffer implementation."""


import os

SOLUTION = r'''package challenge;

import org.reactivestreams.Publisher;
import org.reactivestreams.Subscriber;
import org.reactivestreams.Subscription;
import reactor.core.CoreSubscriber;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Operators;

import java.util.LinkedList;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicIntegerFieldUpdater;
import java.util.concurrent.atomic.AtomicLongFieldUpdater;
import java.util.function.Consumer;
import java.util.function.ToIntFunction;


public class PriorityEvictionBuffer {

    public static <T> Flux<T> create(
            Flux<T> source,
            int capacity,
            ToIntFunction<T> priorityFn,
            Consumer<T> onEvict) {

        Objects.requireNonNull(source, "source must not be null");
        Objects.requireNonNull(priorityFn, "priorityFn must not be null");
        if (capacity <= 0) {
            throw new IllegalArgumentException("capacity must be > 0");
        }

        Publisher<T> publisher = subscriber ->
            source.subscribe(new PriorityEvictionSubscriber<>(subscriber, capacity, priorityFn, onEvict));

        return Flux.from(publisher);
    }

    static class PriorityEvictionSubscriber<T> implements CoreSubscriber<T>, Subscription {

        final Subscriber<? super T> actual;
        final int capacity;
        final ToIntFunction<T> priorityFn;
        final Consumer<T> onEvict;
        final LinkedList<T> queue;

        volatile long requested;
        @SuppressWarnings("rawtypes")
        static final AtomicLongFieldUpdater<PriorityEvictionSubscriber> REQUESTED =
            AtomicLongFieldUpdater.newUpdater(PriorityEvictionSubscriber.class, "requested");

        volatile int wip;
        @SuppressWarnings("rawtypes")
        static final AtomicIntegerFieldUpdater<PriorityEvictionSubscriber> WIP =
            AtomicIntegerFieldUpdater.newUpdater(PriorityEvictionSubscriber.class, "wip");

        Subscription upstream;
        volatile boolean done;
        Throwable error;
        volatile boolean cancelled;

        PriorityEvictionSubscriber(Subscriber<? super T> actual, int capacity,
                                    ToIntFunction<T> priorityFn, Consumer<T> onEvict) {
            this.actual = actual;
            this.capacity = capacity;
            this.priorityFn = priorityFn;
            this.onEvict = onEvict;
            this.queue = new LinkedList<>();
        }

        @Override
        public void onSubscribe(Subscription s) {
            this.upstream = s;
            // Request unbounded from upstream BEFORE notifying downstream.
            // This ensures that synchronous sources (e.g. Flux.range) deliver
            // all elements into the buffer (with eviction) before the downstream
            // subscriber can issue any request(n) that would drain prematurely.
            s.request(Long.MAX_VALUE);
            actual.onSubscribe(this);
        }

        @Override
        public void onNext(T t) {
            if (done) return;

            synchronized (queue) {
                if (queue.size() < capacity) {
                    queue.addLast(t);
                } else {
                    int newPri = priorityFn.applyAsInt(t);
                    T minElem = null;
                    int minPri = Integer.MAX_VALUE;
                    int minIdx = -1;
                    int idx = 0;

                    for (T elem : queue) {
                        int p = priorityFn.applyAsInt(elem);
                        if (p < minPri) {
                            minPri = p;
                            minElem = elem;
                            minIdx = idx;
                        }
                        idx++;
                    }

                    if (newPri > minPri) {
                        queue.remove(minIdx);
                        if (onEvict != null) onEvict.accept(minElem);
                        queue.addLast(t);
                    } else {
                        if (onEvict != null) onEvict.accept(t);
                    }
                }
            }
            drain();
        }

        @Override
        public void onError(Throwable t) {
            if (done) return;
            error = t;
            done = true;
            drain();
        }

        @Override
        public void onComplete() {
            if (done) return;
            done = true;
            drain();
        }

        @Override
        public void request(long n) {
            if (n > 0) {
                Operators.addCap(REQUESTED, this, n);
                drain();
            }
        }

        @Override
        public void cancel() {
            if (!cancelled) {
                cancelled = true;
                upstream.cancel();
                if (WIP.getAndIncrement(this) == 0) {
                    synchronized (queue) {
                        queue.clear();
                    }
                }
            }
        }

        void drain() {
            if (WIP.getAndIncrement(this) != 0) return;

            int missed = 1;

            for (;;) {
                long r = requested;
                long e = 0;

                while (e != r) {
                    if (cancelled) {
                        synchronized (queue) {
                            queue.clear();
                        }
                        return;
                    }

                    boolean d = done;
                    T v;
                    synchronized (queue) {
                        v = queue.isEmpty() ? null : queue.removeFirst();
                    }
                    boolean empty = v == null;

                    if (d && empty) {
                        Throwable err = error;
                        if (err != null) {
                            actual.onError(err);
                        } else {
                            actual.onComplete();
                        }
                        return;
                    }

                    if (empty) break;

                    actual.onNext(v);
                    e++;
                }

                if (e == r) {
                    if (cancelled) {
                        synchronized (queue) {
                            queue.clear();
                        }
                        return;
                    }

                    boolean d = done;
                    boolean empty;
                    synchronized (queue) {
                        empty = queue.isEmpty();
                    }

                    if (d && empty) {
                        Throwable err = error;
                        if (err != null) {
                            actual.onError(err);
                        } else {
                            actual.onComplete();
                        }
                        return;
                    }
                }

                if (e > 0) {
                    REQUESTED.addAndGet(this, -e);
                }

                missed = WIP.addAndGet(this, -missed);
                if (missed == 0) break;
            }
        }
    }
}
'''

target = "/app/src/main/java/challenge/PriorityEvictionBuffer.java"
os.makedirs(os.path.dirname(target), exist_ok=True)
with open(target, "w") as f:
    f.write(SOLUTION)
print(f"Solution written to {target}")

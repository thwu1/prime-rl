#include "mpmc_queue.h"
#include <thread>
#include <vector>
#include <atomic>
#include <cstdio>
#include <algorithm>

static constexpr int NUM_PRODUCERS = 4;
static constexpr int NUM_CONSUMERS = 4;

#ifndef ITEMS_PER_PRODUCER
#define ITEMS_PER_PRODUCER 50000
#endif

static constexpr int QUEUE_SIZE = 1024;

struct Item {
    int producer_id;
    int sequence;
};

int main()
{
    mpmc_bounded_queue<Item> queue(QUEUE_SIZE);

    std::atomic<bool> start{false};
    std::atomic<bool> stop{false};

    std::vector<std::vector<Item>> consumed(NUM_CONSUMERS);
    for (auto& v : consumed)
        v.reserve(ITEMS_PER_PRODUCER);

    // Create producer threads
    std::vector<std::thread> producers;
    for (int p = 0; p < NUM_PRODUCERS; p++) {
        producers.emplace_back([&queue, &start, p]() {
            while (!start.load(std::memory_order_acquire))
                std::this_thread::yield();
            for (int i = 0; i < ITEMS_PER_PRODUCER; i++) {
                Item item{p, i};
                while (!queue.enqueue(item))
                    std::this_thread::yield();
            }
        });
    }

    // Create consumer threads
    std::vector<std::thread> consumers;
    for (int c = 0; c < NUM_CONSUMERS; c++) {
        consumers.emplace_back([&queue, &start, &stop, &consumed, c]() {
            while (!start.load(std::memory_order_acquire))
                std::this_thread::yield();
            while (true) {
                Item item;
                if (queue.dequeue(item)) {
                    consumed[c].push_back(item);
                } else if (stop.load(std::memory_order_acquire)) {
                    // Final drain
                    while (queue.dequeue(item))
                        consumed[c].push_back(item);
                    break;
                } else {
                    std::this_thread::yield();
                }
            }
        });
    }

    // Signal all threads to start
    start.store(true, std::memory_order_release);

    // Wait for all producers to finish
    for (auto& t : producers)
        t.join();

    // Signal consumers to drain and stop
    stop.store(true, std::memory_order_release);

    // Wait for all consumers to finish
    for (auto& t : consumers)
        t.join();

    // ---- Verification ----
    std::vector<Item> all_items;
    for (auto& c : consumed)
        all_items.insert(all_items.end(), c.begin(), c.end());

    int expected = NUM_PRODUCERS * ITEMS_PER_PRODUCER;
    bool pass = true;

    if (static_cast<int>(all_items.size()) != expected) {
        printf("ITEM COUNT MISMATCH: expected %d, got %zu\n",
               expected, all_items.size());
        pass = false;
    }

    // Validate each item is in range
    for (const auto& item : all_items) {
        if (item.producer_id < 0 || item.producer_id >= NUM_PRODUCERS ||
            item.sequence < 0 || item.sequence >= ITEMS_PER_PRODUCER) {
            printf("CORRUPT ITEM: producer_id=%d, sequence=%d\n",
                   item.producer_id, item.sequence);
            pass = false;
            break;
        }
    }

    // Check per-producer completeness: every sequence 0..N-1 appears exactly once
    if (pass) {
        for (int p = 0; p < NUM_PRODUCERS; p++) {
            std::vector<bool> seen(ITEMS_PER_PRODUCER, false);
            int count = 0;
            for (const auto& item : all_items) {
                if (item.producer_id == p) {
                    if (seen[item.sequence]) {
                        printf("DUPLICATE: producer=%d, seq=%d\n",
                               p, item.sequence);
                        pass = false;
                    }
                    seen[item.sequence] = true;
                    count++;
                }
            }
            if (count != ITEMS_PER_PRODUCER) {
                printf("PRODUCER %d: expected %d items, got %d\n",
                       p, ITEMS_PER_PRODUCER, count);
                pass = false;
            }
            if (!pass) break;
        }
    }

    printf("CORRECTNESS: %s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
}

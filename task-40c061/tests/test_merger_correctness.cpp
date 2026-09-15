//
// Tests FeedMerger: sorted output, edge cases, stability.

#include "/app/spsc_queue.hpp"
#include "/app/feed_merger.hpp"
#include <cstdio>
#include <cassert>
#include <vector>
#include <cstdint>

struct Item {
    uint64_t key;
    int source;
};

// ---- Test 1: Basic 4-way merge with interleaved keys ----
static void test_basic_merge() {
    constexpr int K = 4;
    constexpr int N = 100;

    std::vector<SPSCQueue<Item>*> queues;
    for (int i = 0; i < K; ++i) {
        queues.push_back(new SPSCQueue<Item>(N));
    }

    // Source i gets keys: i, i+K, i+2K, ...
    for (int i = 0; i < K; ++i) {
        for (int j = 0; j < N; ++j) {
            Item item{static_cast<uint64_t>(j * K + i), i};
            assert(queues[i]->try_push(item));
        }
    }

    auto key_fn = [](const Item& it) { return it.key; };
    FeedMerger<Item, decltype(key_fn)> merger(queues, key_fn);

    uint64_t last_key = 0;
    int count = 0;
    Item out;
    while (merger.try_merge_one(out)) {
        if (count > 0 && out.key < last_key) {
            fprintf(stderr, "FAIL basic: out of order at %d, key=%lu < %lu\n",
                    count, (unsigned long)out.key, (unsigned long)last_key);
            assert(false);
        }
        last_key = out.key;
        ++count;
    }

    assert(count == K * N);
    for (auto* q : queues) delete q;
}

// ---- Test 2: Single source (K=1) ----
static void test_single_source() {
    SPSCQueue<Item> q(50);
    for (int i = 0; i < 50; ++i) {
        q.try_push(Item{static_cast<uint64_t>(i * 2), 0});
    }

    std::vector<SPSCQueue<Item>*> queues = {&q};
    auto key_fn = [](const Item& it) { return it.key; };
    FeedMerger<Item, decltype(key_fn)> merger(queues, key_fn);

    int count = 0;
    Item out;
    while (merger.try_merge_one(out)) {
        assert(out.key == static_cast<uint64_t>(count * 2));
        ++count;
    }
    assert(count == 50);
}

// ---- Test 3: One source empty, one has data ----
static void test_one_empty_source() {
    SPSCQueue<Item> q1(50);
    SPSCQueue<Item> q2(50);

    for (int i = 0; i < 30; ++i) {
        q1.try_push(Item{static_cast<uint64_t>(i), 0});
    }
    // q2 stays empty

    std::vector<SPSCQueue<Item>*> queues = {&q1, &q2};
    auto key_fn = [](const Item& it) { return it.key; };
    FeedMerger<Item, decltype(key_fn)> merger(queues, key_fn);

    int count = 0;
    Item out;
    while (merger.try_merge_one(out)) {
        ++count;
    }
    assert(count == 30);
}

// ---- Test 4: Stability — equal keys from different sources ----
static void test_stability() {
    constexpr int K = 3;
    SPSCQueue<Item> q0(10), q1(10), q2(10);

    // All three sources have identical keys: 0, 1, 2, 3, 4
    for (int i = 0; i < 5; ++i) {
        q0.try_push(Item{static_cast<uint64_t>(i), 0});
        q1.try_push(Item{static_cast<uint64_t>(i), 1});
        q2.try_push(Item{static_cast<uint64_t>(i), 2});
    }

    std::vector<SPSCQueue<Item>*> queues = {&q0, &q1, &q2};
    auto key_fn = [](const Item& it) { return it.key; };
    FeedMerger<Item, decltype(key_fn)> merger(queues, key_fn);

    // Expected order: for each key value, sources 0, 1, 2 in order
    Item out;
    for (int key = 0; key < 5; ++key) {
        for (int src = 0; src < K; ++src) {
            assert(merger.try_merge_one(out));
            if (out.key != static_cast<uint64_t>(key) || out.source != src) {
                fprintf(stderr,
                        "FAIL stability: expected key=%d src=%d, "
                        "got key=%lu src=%d\n",
                        key, src, (unsigned long)out.key, out.source);
                assert(false);
            }
        }
    }
    assert(!merger.try_merge_one(out));
}

// ---- Test 5: Non-power-of-2 source count (K=3) ----
static void test_non_power_of_2_sources() {
    SPSCQueue<Item> q0(20), q1(20), q2(20);

    q0.try_push(Item{1, 0}); q0.try_push(Item{4, 0}); q0.try_push(Item{7, 0});
    q1.try_push(Item{2, 1}); q1.try_push(Item{5, 1}); q1.try_push(Item{8, 1});
    q2.try_push(Item{3, 2}); q2.try_push(Item{6, 2}); q2.try_push(Item{9, 2});

    std::vector<SPSCQueue<Item>*> queues = {&q0, &q1, &q2};
    auto key_fn = [](const Item& it) { return it.key; };
    FeedMerger<Item, decltype(key_fn)> merger(queues, key_fn);

    Item out;
    for (uint64_t expected = 1; expected <= 9; ++expected) {
        assert(merger.try_merge_one(out));
        if (out.key != expected) {
            fprintf(stderr, "FAIL non-pow2: expected key=%lu, got %lu\n",
                    (unsigned long)expected, (unsigned long)out.key);
            assert(false);
        }
    }
    assert(!merger.try_merge_one(out));
}

// ---- Test 6: Large K (K=16) ----
static void test_large_k() {
    constexpr int K = 16;
    constexpr int N = 50;

    std::vector<SPSCQueue<Item>*> queues;
    for (int i = 0; i < K; ++i) {
        auto* q = new SPSCQueue<Item>(N);
        for (int j = 0; j < N; ++j) {
            q->try_push(Item{static_cast<uint64_t>(j * K + i), i});
        }
        queues.push_back(q);
    }

    auto key_fn = [](const Item& it) { return it.key; };
    FeedMerger<Item, decltype(key_fn)> merger(queues, key_fn);

    uint64_t last = 0;
    int count = 0;
    Item out;
    while (merger.try_merge_one(out)) {
        if (count > 0) {
            assert(out.key >= last);
        }
        last = out.key;
        ++count;
    }
    assert(count == K * N);

    for (auto* q : queues) delete q;
}

// ---- Test 7: Unequal source lengths ----
static void test_unequal_lengths() {
    SPSCQueue<Item> q0(200), q1(200), q2(200);

    // q0: 100 items, q1: 50 items, q2: 10 items
    for (int i = 0; i < 100; ++i)
        q0.try_push(Item{static_cast<uint64_t>(i * 3), 0});
    for (int i = 0; i < 50; ++i)
        q1.try_push(Item{static_cast<uint64_t>(i * 3 + 1), 1});
    for (int i = 0; i < 10; ++i)
        q2.try_push(Item{static_cast<uint64_t>(i * 3 + 2), 2});

    std::vector<SPSCQueue<Item>*> queues = {&q0, &q1, &q2};
    auto key_fn = [](const Item& it) { return it.key; };
    FeedMerger<Item, decltype(key_fn)> merger(queues, key_fn);

    uint64_t last = 0;
    int count = 0;
    Item out;
    while (merger.try_merge_one(out)) {
        if (count > 0) {
            assert(out.key >= last);
        }
        last = out.key;
        ++count;
    }
    assert(count == 160);  // 100 + 50 + 10
}

int main() {
    test_basic_merge();
    test_single_source();
    test_one_empty_source();
    test_stability();
    test_non_power_of_2_sources();
    test_large_k();
    test_unequal_lengths();

    printf("PASS\n");
    return 0;
}

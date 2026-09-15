// trading_sim.cpp — Integration test: SPSC queues + K-way merger
// Simulates a multi-feed market data pipeline.
//
// 4 exchange feeds, each producing sorted ticks, are merged into a single
// globally-sorted stream by the FeedMerger.
//
// Compile: make
// Run:     ./trading_sim

#include "spsc_queue.hpp"
#include "feed_merger.hpp"
#include "market_data.hpp"
#include <iostream>
#include <vector>
#include <cassert>
#include <cstdint>

int main() {
    constexpr int K = 4;
    constexpr int TICKS_PER_SOURCE = 2500;

    // Create one SPSC queue per exchange feed
    std::vector<SPSCQueue<Tick>*> queues;
    for (int i = 0; i < K; ++i) {
        queues.push_back(new SPSCQueue<Tick>(TICKS_PER_SOURCE));
    }

    // Pre-fill: source i gets timestamps i, i+K, i+2K, ...
    // Each source's timestamps are strictly ascending.
    for (int i = 0; i < K; ++i) {
        for (int j = 0; j < TICKS_PER_SOURCE; ++j) {
            Tick t;
            t.timestamp = static_cast<uint64_t>(j * K + i);
            t.source_id = static_cast<uint32_t>(i);
            t.price = 100.0 + j * 0.01;
            t.quantity = 10.0 + (j % 100);
            bool ok = queues[i]->try_push(t);
            if (!ok) {
                std::cerr << "FAIL: could not push tick " << j
                          << " to source " << i << "\n";
                return 1;
            }
        }
    }

    // Merge all feeds in timestamp order
    auto key_fn = [](const Tick& t) { return t.timestamp; };
    FeedMerger<Tick, decltype(key_fn)> merger(queues, key_fn);

    uint64_t last_ts = 0;
    int count = 0;
    Tick t;
    while (merger.try_merge_one(t)) {
        if (count > 0 && t.timestamp < last_ts) {
            std::cerr << "OUT OF ORDER at position " << count
                      << ": timestamp " << t.timestamp
                      << " < previous " << last_ts << "\n";
            return 1;
        }
        last_ts = t.timestamp;
        ++count;
    }

    if (count != K * TICKS_PER_SOURCE) {
        std::cerr << "WRONG COUNT: got " << count
                  << ", expected " << K * TICKS_PER_SOURCE << "\n";
        return 1;
    }

    std::cout << "PASS: merged " << count << " ticks in timestamp order\n";

    for (auto* q : queues) delete q;
    return 0;
}

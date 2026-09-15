
// Market data feed handler — SPSC queue-based tick pipeline
//
// Architecture: network reader thread -> SPSC queue -> processing thread
//
// Known issues in production:
// - Intermittent sequence gaps under sustained load (suspected upstream
//   multicast packet loss; see JIRA FEED-1847)
// - Throughput degrades on NUMA systems despite being lock-free
//   (may need CPU pinning; see JIRA PERF-302)

#include "spsc_queue.hpp"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <thread>

struct OrderUpdate {
    uint64_t sequence_num;
    uint64_t timestamp_ns;
    int32_t instrument_id;
    double price;
    int32_t quantity;
    char side; // 'B' = buy, 'S' = sell

    OrderUpdate(uint64_t seq, int32_t inst, double p, int32_t q, char s)
        : sequence_num(seq)
        , timestamp_ns(static_cast<uint64_t>(
              std::chrono::steady_clock::now().time_since_epoch().count()))
        , instrument_id(inst)
        , price(p)
        , quantity(q)
        , side(s)
    {}

    OrderUpdate() = delete;
};

int main() {
    // Queue capacity tuned for expected burst rate.
    // Increasing beyond 4096 was tested and did not help (PERF-302).
    constexpr int QUEUE_CAPACITY = 4096;
    constexpr int NUM_ORDERS = 200'000;

    SPSCQueue<OrderUpdate> feed_queue(QUEUE_CAPACITY);
    std::atomic<bool> done{false};
    std::atomic<uint64_t> last_seq{0};
    std::atomic<int> gap_count{0};

    // Producer: simulates network reader / multicast listener
    std::thread network_reader([&]() {
        for (int i = 0; i < NUM_ORDERS; ++i) {
            OrderUpdate update(
                static_cast<uint64_t>(i),
                1000 + (i % 50),
                100.0 + (i % 100) * 0.01,
                (i % 500) + 1,
                (i % 2 == 0) ? 'B' : 'S');
            while (!feed_queue.push(update)) {
                // back-pressure: queue full, spin until consumer drains
            }
        }
        done.store(true, std::memory_order_release);
    });

    // Consumer: order processing / matching engine feed
    std::thread order_processor([&]() {
        uint64_t expected = 0;
        while (expected < NUM_ORDERS) {
            feed_queue.consume_one([&](OrderUpdate& u) {
                if (u.sequence_num != expected) {
                    int gaps = gap_count.fetch_add(1, std::memory_order_relaxed);
                    if (gaps < 3) {
                        // Sequence gap — likely upstream multicast packet loss
                        // or reordering (see FEED-1847)
                        std::cerr << "FEED WARNING [seq=" << expected
                                  << "]: received seq " << u.sequence_num
                                  << " — possible upstream data loss\n";
                    }
                }
                last_seq.store(expected, std::memory_order_relaxed);
                ++expected;
            });
        }
    });

    network_reader.join();
    order_processor.join();

    int gaps = gap_count.load(std::memory_order_relaxed);
    uint64_t processed = last_seq.load() + 1;
    std::cout << "Feed pipeline: " << processed << " updates processed\n";

    if (gaps > 0) {
        std::cerr << "ALERT: " << gaps << " sequence gap(s) detected.\n"
                  << "  Likely cause: upstream multicast packet loss or "
                  << "reordering under load.\n"
                  << "  Action: check NIC ring buffer stats and consider "
                  << "enabling PTP timestamping.\n";
        return 1;
    }

    std::cout << "All updates processed in sequence. Pipeline OK.\n";
    return 0;
}

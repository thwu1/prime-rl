
#include <thread>
#include <chrono>
#include <iostream>
#include <mutex>
#include <new>
#include <memory>
#include <algorithm>
#include <cstdint>

// ============================================================
// Mutex baseline for comparison (DO NOT MODIFY)
// ============================================================
template <typename T>
class MutexSPSCQueue {
public:
    explicit MutexSPSCQueue(std::size_t capacity)
        : capacity_(capacity + 1)
        , buffer_(static_cast<T*>(::operator new(sizeof(T) * capacity_)))
        , head_(0)
        , tail_(0)
    {}

    ~MutexSPSCQueue() {
        while (head_ != tail_) {
            std::destroy_at(&buffer_[head_]);
            head_ = (head_ + 1) % capacity_;
        }
        ::operator delete(buffer_);
    }

    MutexSPSCQueue(const MutexSPSCQueue&) = delete;
    MutexSPSCQueue& operator=(const MutexSPSCQueue&) = delete;

    bool push(const T& item) {
        std::lock_guard<std::mutex> lock(mtx_);
        std::size_t next_tail = (tail_ + 1) % capacity_;
        if (next_tail == head_) return false;
        std::construct_at(&buffer_[tail_], item);
        tail_ = next_tail;
        return true;
    }

    template <typename Func>
    bool consume_one(Func&& func) {
        std::lock_guard<std::mutex> lock(mtx_);
        if (head_ == tail_) return false;
        func(buffer_[head_]);
        std::destroy_at(&buffer_[head_]);
        head_ = (head_ + 1) % capacity_;
        return true;
    }

private:
    std::size_t capacity_;
    T* buffer_;
    std::size_t head_;
    std::size_t tail_;
    std::mutex mtx_;
};

// ============================================================
// Agent's implementation
// ============================================================
#include "spsc_queue.hpp"

// ============================================================
// Benchmark harness
// ============================================================
template <typename QueueType>
double run_benchmark(int64_t num_ops, int queue_size) {
    QueueType q(queue_size);

    auto start = std::chrono::steady_clock::now();

    std::thread producer([&]() {
        for (int64_t i = 0; i < num_ops; ++i) {
            while (!q.push(i)) {}
        }
    });

    int64_t total = 0;
    std::thread consumer([&]() {
        int64_t count = 0;
        while (count < num_ops) {
            q.consume_one([&](int64_t val) {
                total += val;
                ++count;
            });
        }
    });

    producer.join();
    consumer.join();

    auto end = std::chrono::steady_clock::now();
    double seconds = std::chrono::duration<double>(end - start).count();
    return static_cast<double>(num_ops) / seconds;
}

int main() {
    const int64_t NUM_OPS = 5'000'000;
    const int QUEUE_SIZE = 4096;

    // Warmup runs
    run_benchmark<SPSCQueue<int64_t>>(100'000, QUEUE_SIZE);
    run_benchmark<MutexSPSCQueue<int64_t>>(100'000, QUEUE_SIZE);

    // Benchmark runs - interleaved to reduce environmental bias
    double best_lockfree = 0, best_mutex = 0;
    for (int i = 0; i < 3; ++i) {
        double lf = run_benchmark<SPSCQueue<int64_t>>(NUM_OPS, QUEUE_SIZE);
        double mx = run_benchmark<MutexSPSCQueue<int64_t>>(NUM_OPS, QUEUE_SIZE);
        best_lockfree = std::max(best_lockfree, lf);
        best_mutex = std::max(best_mutex, mx);
        std::cerr << "Run " << (i+1) << ": lockfree=" << lf
                  << " mutex=" << mx << std::endl;
    }

    std::cout << "LOCKFREE_BEST: " << best_lockfree << std::endl;
    std::cout << "MUTEX_BEST: " << best_mutex << std::endl;
    std::cout << "SPEEDUP: " << (best_lockfree / best_mutex) << std::endl;

    return 0;
}

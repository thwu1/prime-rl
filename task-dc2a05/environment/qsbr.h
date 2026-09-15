#pragma once


// Quiescent State-Based Reclamation (QSBR)
// A simplified, header-only QSBR implementation for safe deferred
// destruction of shared objects in lock-free data structures.
//
// Usage:
//   1. Each thread calls createContext() before using the data structure.
//   2. Periodically, each thread calls update(ctx) at a point when it is NOT
//      in the middle of an operation (a "quiescent state").
//   3. When an old object should be destroyed, call enqueue(callback).
//      The callback will be invoked after ALL registered threads have
//      passed through at least one quiescent state since the enqueue.
//   4. Call destroyContext(ctx) when a thread is done using the data structure.
//   5. Call flush() to force-invoke all pending callbacks (e.g. in destructor).

#include <atomic>
#include <functional>
#include <mutex>
#include <vector>
#include <cstdint>
#include <cassert>

class QSBR {
public:
    using Context = uint16_t;

    QSBR() = default;
    ~QSBR() = default;

    QSBR(const QSBR&) = delete;
    QSBR& operator=(const QSBR&) = delete;

    Context createContext() {
        std::lock_guard<std::mutex> lock(m_mutex);
        for (size_t i = 0; i < m_slots.size(); i++) {
            if (!m_slots[i].inUse) {
                m_slots[i].inUse = true;
                m_slots[i].wasQuiescent = false;
                m_remaining++;
                return static_cast<Context>(i);
            }
        }
        Context id = static_cast<Context>(m_slots.size());
        m_slots.push_back({true, false});
        m_remaining++;
        return id;
    }

    void destroyContext(Context ctx) {
        std::lock_guard<std::mutex> lock(m_mutex);
        assert(ctx < m_slots.size() && m_slots[ctx].inUse);
        if (!m_slots[ctx].wasQuiescent) {
            m_remaining--;
        }
        m_slots[ctx].inUse = false;
        m_slots[ctx].wasQuiescent = false;
        tryEndInterval();
    }

    void enqueue(std::function<void()> callback) {
        std::lock_guard<std::mutex> lock(m_mutex);
        m_currentCallbacks.push_back(std::move(callback));
    }

    void update(Context ctx) {
        std::lock_guard<std::mutex> lock(m_mutex);
        assert(ctx < m_slots.size() && m_slots[ctx].inUse);
        if (!m_slots[ctx].wasQuiescent) {
            m_slots[ctx].wasQuiescent = true;
            m_remaining--;
            tryEndInterval();
        }
    }

    void flush() {
        std::lock_guard<std::mutex> lock(m_mutex);
        for (auto& cb : m_previousCallbacks) cb();
        m_previousCallbacks.clear();
        for (auto& cb : m_currentCallbacks) cb();
        m_currentCallbacks.clear();
    }

private:
    struct Slot {
        bool inUse = false;
        bool wasQuiescent = false;
    };

    std::mutex m_mutex;
    std::vector<Slot> m_slots;
    int m_remaining = 0;
    std::vector<std::function<void()>> m_currentCallbacks;
    std::vector<std::function<void()>> m_previousCallbacks;

    void tryEndInterval() {
        if (m_remaining == 0) {
            for (auto& cb : m_previousCallbacks) cb();
            m_previousCallbacks = std::move(m_currentCallbacks);
            m_currentCallbacks.clear();
            m_remaining = 0;
            for (auto& s : m_slots) {
                if (s.inUse) {
                    s.wasQuiescent = false;
                    m_remaining++;
                }
            }
        }
    }
};

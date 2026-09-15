#pragma once

#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

// ---------------------------------------------------------------------------
// Sentinels
// ---------------------------------------------------------------------------
static constexpr uint64_t EMPTY_KEY   = 0;
static constexpr uint64_t EMPTY_VAL   = 0;
static constexpr uint64_t REDIRECT_VAL = 1;  // Reserved for table migration

// ---------------------------------------------------------------------------
// MurmurHash3 64-bit finalizer — used only for probe-position computation
// ---------------------------------------------------------------------------
inline uint64_t murmur_hash64(uint64_t k) {
    k ^= k >> 33;
    k *= 0xff51afd7ed558ccdULL;
    k ^= k >> 33;
    k *= 0xc4ceb9fe1a85ec53ULL;
    k ^= k >> 33;
    return k;
}

// ---------------------------------------------------------------------------
// Cell: one slot in the hash table
// ---------------------------------------------------------------------------
struct Cell {
    std::atomic<uint64_t> key{0};
    std::atomic<uint64_t> value{0};
};

// ---------------------------------------------------------------------------
// Table: fixed-size open-addressing table with linear probing
// ---------------------------------------------------------------------------
class Table {
public:
    Cell*       const cells;
    size_t      const capacity;
    size_t      const mask;
    std::atomic<size_t> population{0};
    std::atomic<bool>   frozen{false};   // Available for migration control

    explicit Table(size_t cap)
        : cells(new Cell[cap]()), capacity(cap), mask(cap - 1)
    {
        assert(cap > 0 && (cap & (cap - 1)) == 0);
    }

    ~Table() { delete[] cells; }
    Table(const Table&) = delete;
    Table& operator=(const Table&) = delete;

    // Find the cell that holds `key`. Returns nullptr if the key is absent.
    Cell* find(uint64_t key) const {
        size_t idx = murmur_hash64(key) & mask;
        for (size_t i = 0; i < capacity; ++i) {
            Cell& c = cells[(idx + i) & mask];
            uint64_t k = c.key.load(std::memory_order_acquire);
            if (k == key)      return &c;
            if (k == EMPTY_KEY) return nullptr;
        }
        return nullptr;
    }

    enum InsertResult { INSERTED, FOUND, OVERFLOW };

    // Insert `key` or find an existing cell for it.
    InsertResult insertOrFind(uint64_t key, Cell*& out) {
        size_t idx = murmur_hash64(key) & mask;
        for (size_t i = 0; i < capacity; ++i) {
            Cell& c = cells[(idx + i) & mask];
            uint64_t k = c.key.load(std::memory_order_acquire);

            if (k == key) {
                out = &c;
                return FOUND;
            }

            if (k == EMPTY_KEY) {
                uint64_t expected = EMPTY_KEY;
                if (c.key.compare_exchange_strong(
                        expected, key,
                        std::memory_order_acq_rel,
                        std::memory_order_acquire)) {
                    population.fetch_add(1, std::memory_order_relaxed);
                    out = &c;
                    return INSERTED;
                }
                // CAS failed — another thread claimed this slot.
                if (expected == key) {
                    out = &c;
                    return FOUND;
                }
                // A different key landed here; continue probing.
            }
        }
        return OVERFLOW;
    }
};

// ---------------------------------------------------------------------------
// QSBR — Quiescent-State-Based Reclamation
//
// Two-phase interval tracking:
//   • Callbacks enqueued during interval N move to "previous" when N ends.
//   • When interval N+1 ends the "previous" callbacks are executed.
//   • An interval ends when every active context has called update() once.
// ---------------------------------------------------------------------------
class QSBR {
public:
    using Context = uint16_t;

private:
    struct Slot {
        bool active    = false;
        bool quiesced  = false;
    };

    std::mutex                           m_mtx;
    std::vector<Slot>                    m_slots;
    size_t                               m_num_active    = 0;
    size_t                               m_num_remaining = 0;
    std::vector<std::function<void()>>   m_current;
    std::vector<std::function<void()>>   m_previous;

    // Advance the interval if all active contexts have been quiescent.
    void tryAdvance() {
        if (m_num_remaining == 0 && m_num_active > 0) {
            // Execute callbacks from the previous interval.
            for (auto& cb : m_previous) cb();
            m_previous.clear();
            // Promote current → previous.
            m_previous.swap(m_current);
            // Reset quiescent flags for the next interval.
            for (auto& s : m_slots) {
                if (s.active) s.quiesced = false;
            }
            m_num_remaining = m_num_active;
        }
    }

public:
    Context createContext() {
        std::lock_guard<std::mutex> g(m_mtx);
        for (size_t i = 0; i < m_slots.size(); ++i) {
            if (!m_slots[i].active) {
                m_slots[i] = {true, false};
                ++m_num_active;
                ++m_num_remaining;
                return static_cast<Context>(i);
            }
        }
        m_slots.push_back({true, false});
        ++m_num_active;
        ++m_num_remaining;
        return static_cast<Context>(m_slots.size() - 1);
    }

    void destroyContext(Context ctx) {
        std::lock_guard<std::mutex> g(m_mtx);
        if (m_slots[ctx].active) {
            if (!m_slots[ctx].quiesced) --m_num_remaining;
            m_slots[ctx].active = false;
            --m_num_active;
            tryAdvance();
        }
    }

    void enqueue(std::function<void()> cb) {
        std::lock_guard<std::mutex> g(m_mtx);
        m_current.push_back(std::move(cb));
    }

    void update(Context ctx) {
        std::lock_guard<std::mutex> g(m_mtx);
        if (m_slots[ctx].active && !m_slots[ctx].quiesced) {
            m_slots[ctx].quiesced = true;
            --m_num_remaining;
            tryAdvance();
        }
    }

    // Force-execute all pending callbacks (used in destructor).
    void flush() {
        std::lock_guard<std::mutex> g(m_mtx);
        for (auto& cb : m_previous) cb();
        for (auto& cb : m_current)  cb();
        m_previous.clear();
        m_current.clear();
    }
};

// ---------------------------------------------------------------------------
// ConcurrentMap — resizable lock-free hash map with QSBR reclamation
//
// The single-table operations (get, assign, erase) are implemented below.
// They work correctly on a fixed-size table.  However, when the load factor
// exceeds 75%, doResize() is called and its current implementation simply
// allocates a new empty table — discarding all existing entries.
//
// Your task is to design and implement a correct concurrent table migration
// protocol in doResize(), and to update get/assign/erase (and possibly
// Table::insertOrFind) to handle the intermediate states during migration.
// ---------------------------------------------------------------------------
class ConcurrentMap {
public:
    using Context = QSBR::Context;

    explicit ConcurrentMap(size_t initial_capacity = 64) {
        size_t cap = 1;
        while (cap < initial_capacity) cap <<= 1;
        m_root.store(new Table(cap), std::memory_order_relaxed);
    }

    ~ConcurrentMap() {
        m_qsbr.flush();
        delete m_root.load(std::memory_order_relaxed);
    }

    // ---- Thread registration (QSBR) ----
    Context registerThread()            { return m_qsbr.createContext(); }
    void    unregisterThread(Context c) { m_qsbr.destroyContext(c); }
    void    quiescent(Context c)        { m_qsbr.update(c); }

    // ---- Map operations ----

    uint64_t get(uint64_t key) {
        Table* t = m_root.load(std::memory_order_acquire);
        Cell* c = t->find(key);
        if (!c) return 0;
        return c->value.load(std::memory_order_acquire);
    }

    uint64_t assign(uint64_t key, uint64_t value) {
        for (;;) {
            Table* t = m_root.load(std::memory_order_acquire);
            Cell* cell;
            Table::InsertResult r = t->insertOrFind(key, cell);
            if (r == Table::OVERFLOW) {
                doResize(t);
                continue;
            }

            // CAS loop: write the new value.
            uint64_t old_val = cell->value.load(std::memory_order_acquire);
            while (true) {
                if (cell->value.compare_exchange_weak(
                        old_val, value,
                        std::memory_order_acq_rel,
                        std::memory_order_acquire)) {
                    // Successfully wrote the value.
                    if (r == Table::INSERTED) {
                        size_t pop = t->population.load(std::memory_order_relaxed);
                        if (pop * 4 > t->capacity * 3) doResize(t);
                    }
                    return old_val;
                }
                // CAS failed — old_val updated; retry.
            }
        }
    }

    uint64_t erase(uint64_t key) {
        Table* t = m_root.load(std::memory_order_acquire);
        Cell* c = t->find(key);
        if (!c) return 0;

        uint64_t old_val = c->value.load(std::memory_order_acquire);
        while (old_val != EMPTY_VAL) {
            if (c->value.compare_exchange_weak(
                    old_val, EMPTY_VAL,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return old_val;
            }
        }
        return 0;
    }

private:
    std::atomic<Table*> m_root{nullptr};
    QSBR                m_qsbr;
    std::mutex           m_resize_mtx;

    // Double the table capacity.  The mutex serialises concurrent resize
    // attempts.
    //
    // CURRENT STATE: allocates a new table but does NOT migrate entries.
    // All data in the old table is lost.
    //
    // You must redesign this method (and adjust the map operations above)
    // so that every entry in the old table is safely copied to the new one
    // before it is published, even while other threads are concurrently
    // reading, writing, and erasing entries.
    //
    // Available building blocks you may find useful:
    //   - REDIRECT_VAL sentinel (defined above)
    //   - Table::frozen flag
    //   - QSBR system (m_qsbr) for safe deferred deallocation
    void doResize(Table* old_t) {
        std::lock_guard<std::mutex> lock(m_resize_mtx);

        // Re-check after acquiring the mutex — another thread may have
        // already completed a resize.
        Table* cur = m_root.load(std::memory_order_acquire);
        if (cur != old_t) return;
        if (cur->population.load(std::memory_order_relaxed) * 4
                <= cur->capacity * 3)
            return;

        Table* new_t = new Table(old_t->capacity * 2);

        // ---------------------------------------------------------------
        // TODO: Migrate entries from old_t → new_t here.
        //
        // The current implementation simply publishes the empty new table,
        // which means all existing entries are silently discarded.
        // ---------------------------------------------------------------

        m_root.store(new_t, std::memory_order_release);

        // WARNING: old_t is leaked and its entries are lost.
    }
};

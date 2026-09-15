#pragma once


// Lock-free concurrent hash map with dynamic resizing and QSBR reclamation.
//
// Design:
//   - Open addressing with linear probing over a flat Cell array.
//   - Keys and values are uint64_t. Key 0 is reserved (NullKey = empty slot).
//     Value 0 means empty/erased (NullValue). Value 1 means the cell has been
//     migrated to a successor table (Redirect).
//   - Resizing creates a new Table with double capacity. Each cell in the old
//     table is redirected (value CAS'd to Redirect) and its captured value is
//     inserted into the new table. The root pointer is updated after all cells
//     are migrated. Old tables are destroyed via QSBR.
//
// Thread lifecycle:
//   Each thread must call registerThread() before using the map and
//   unregisterThread() when done. Between operations, threads should
//   periodically call quiescent() so QSBR can reclaim old tables.

#include <atomic>
#include <cstdint>
#include <cstddef>
#include "qsbr.h"
#include "hash_util.h"

static constexpr uint64_t NullKey   = 0;
static constexpr uint64_t NullValue = 0;
static constexpr uint64_t Redirect  = 1;

class ConcurrentHashMap {
public:
    struct Cell {
        std::atomic<uint64_t> key{0};
        std::atomic<uint64_t> value{0};
    };

    struct Table {
        Cell* cells = nullptr;
        size_t sizeMask = 0;                          // capacity - 1
        std::atomic<size_t> population{0};             // cells with claimed keys
        std::atomic<Table*> newTable{nullptr};         // migration destination
        std::atomic<size_t> migrateIndex{0};           // next chunk to claim
        std::atomic<size_t> migrateComplete{0};        // chunks fully migrated

        static Table* create(size_t capacity);
        void destroy();
    };

    explicit ConcurrentHashMap(size_t initialCapacity = 64);
    ~ConcurrentHashMap();

    ConcurrentHashMap(const ConcurrentHashMap&) = delete;
    ConcurrentHashMap& operator=(const ConcurrentHashMap&) = delete;

    // Insert or update. key must not be 0. value must not be 0 or 1.
    // Returns previous value (0 if new insertion).
    uint64_t insert(uint64_t key, uint64_t value);

    // Lookup. Returns value, or 0 if not found.
    uint64_t get(uint64_t key);

    // Erase. Returns previous value, or 0 if not found.
    uint64_t erase(uint64_t key);

    // QSBR thread management.
    uint16_t registerThread();
    void unregisterThread(uint16_t ctx);
    void quiescent(uint16_t ctx);

    // Expose root for testing / debugging.
    Table* getRoot() const { return m_root.load(std::memory_order_acquire); }

private:
    std::atomic<Table*> m_root;
    QSBR m_qsbr;

    void beginMigration(Table* table);
    void helpMigrate(Table* table);
    void migrateRange(Table* src, Table* dst, size_t begin, size_t end);
};

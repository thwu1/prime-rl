#!/usr/bin/env python3
"""
Generate the concurrent hash map implementation.
This script constructs the C++ source from verified algorithmic components.

"""
import os

IMPL = r'''
#include "concurrent_hashmap.h"
#include "hash_util.h"
#include <cassert>
#include <algorithm>
#include <thread>

// ============================================================
// Anonymous-namespace helpers (not class members)
// ============================================================

namespace {

// Linear-probe search for an existing key. Returns cell pointer or nullptr.
ConcurrentHashMap::Cell* findCell(
    uint64_t key, ConcurrentHashMap::Table* table)
{
    uint64_t h = murmurHash3_64(key);
    size_t idx = h & table->sizeMask;
    for (size_t i = 0; i <= table->sizeMask; i++) {
        auto& cell = table->cells[idx];
        uint64_t k = cell.key.load(std::memory_order_acquire);
        if (k == key) return &cell;
        if (k == NullKey) return nullptr;  // End of probe chain
        idx = (idx + 1) & table->sizeMask;
    }
    return nullptr;
}

// Find existing cell for key, or claim a new one via CAS.
// Sets overflow=true if the table is full. Never returns nullptr
// unless overflow is set.
ConcurrentHashMap::Cell* insertOrFind(
    uint64_t key, ConcurrentHashMap::Table* table, bool& overflow)
{
    uint64_t h = murmurHash3_64(key);
    size_t idx = h & table->sizeMask;
    overflow = false;
    for (size_t i = 0; i <= table->sizeMask; i++) {
        auto& cell = table->cells[idx];
        uint64_t k = cell.key.load(std::memory_order_acquire);
        if (k == key) return &cell;
        if (k == NullKey) {
            // Try to claim this cell for our key.
            uint64_t expected = NullKey;
            if (cell.key.compare_exchange_strong(
                    expected, key,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                table->population.fetch_add(1, std::memory_order_relaxed);
                return &cell;
            }
            // CAS failed — another thread claimed the cell.
            if (expected == key) return &cell;  // Same key — reuse.
            // Different key — continue probing.
        }
        idx = (idx + 1) & table->sizeMask;
    }
    overflow = true;
    return nullptr;
}

}  // anonymous namespace

// ============================================================
// Table lifecycle
// ============================================================

ConcurrentHashMap::Table* ConcurrentHashMap::Table::create(size_t capacity) {
    assert(capacity >= 4 && (capacity & (capacity - 1)) == 0);
    Table* t = new Table();
    t->cells     = new Cell[capacity]();  // Zero-init (key=0, value=0)
    t->sizeMask  = capacity - 1;
    return t;
}

void ConcurrentHashMap::Table::destroy() {
    delete[] cells;
    delete this;
}

// ============================================================
// Constructor / Destructor
// ============================================================

ConcurrentHashMap::ConcurrentHashMap(size_t initialCapacity) {
    size_t cap = 16;
    while (cap < initialCapacity) cap <<= 1;
    m_root.store(Table::create(cap), std::memory_order_release);
}

ConcurrentHashMap::~ConcurrentHashMap() {
    m_qsbr.flush();  // Execute all pending destruction callbacks.
    Table* table = m_root.load(std::memory_order_relaxed);
    while (table) {
        Table* next = table->newTable.load(std::memory_order_relaxed);
        table->destroy();
        table = next;
    }
}

// ============================================================
// QSBR delegation
// ============================================================

uint16_t ConcurrentHashMap::registerThread()           { return m_qsbr.createContext(); }
void     ConcurrentHashMap::unregisterThread(uint16_t c) { m_qsbr.destroyContext(c); }
void     ConcurrentHashMap::quiescent(uint16_t c)        { m_qsbr.update(c); }

// ============================================================
// Migration
// ============================================================

void ConcurrentHashMap::beginMigration(Table* table) {
    size_t newCap = (table->sizeMask + 1) * 2;
    Table* dst = Table::create(newCap);

    Table* expected = nullptr;
    if (!table->newTable.compare_exchange_strong(
            expected, dst,
            std::memory_order_acq_rel,
            std::memory_order_acquire)) {
        // Another thread already started the migration.
        dst->destroy();
    }
    helpMigrate(table);
}

void ConcurrentHashMap::helpMigrate(Table* table) {
    Table* dst = table->newTable.load(std::memory_order_acquire);
    if (!dst) return;

    const size_t totalCells = table->sizeMask + 1;
    constexpr size_t CHUNK = 64;
    const size_t numChunks = (totalCells + CHUNK - 1) / CHUNK;

    // Claim and migrate chunks.
    for (;;) {
        size_t begin = table->migrateIndex.fetch_add(
            CHUNK, std::memory_order_acq_rel);
        if (begin >= totalCells) break;
        size_t end = std::min(begin + CHUNK, totalCells);
        migrateRange(table, dst, begin, end);
        table->migrateComplete.fetch_add(1, std::memory_order_release);
    }

    // Spin until every chunk has been fully migrated by whichever thread
    // claimed it.  This guarantees that all values are in the new table
    // before we publish the new root.
    while (table->migrateComplete.load(std::memory_order_acquire) < numChunks) {
        std::this_thread::yield();
    }

    // Publish the new table as root.  Exactly one thread succeeds.
    Table* expectedRoot = table;
    if (m_root.compare_exchange_strong(
            expectedRoot, dst,
            std::memory_order_acq_rel,
            std::memory_order_acquire)) {
        // Enqueue the old table for deferred destruction via QSBR.
        m_qsbr.enqueue([table]() { table->destroy(); });
    }
}

void ConcurrentHashMap::migrateRange(
    Table* src, Table* dst, size_t begin, size_t end)
{
    for (size_t i = begin; i < end; i++) {
        auto& cell = src->cells[i];
        uint64_t key = cell.key.load(std::memory_order_acquire);
        if (key == NullKey) continue;  // Empty slot — skip.

        // Redirect the cell's value to Redirect, capturing the old value.
        for (;;) {
            uint64_t val = cell.value.load(std::memory_order_acquire);
            if (val == Redirect) break;  // Already migrated by another thread.

            uint64_t expected = val;
            if (cell.value.compare_exchange_strong(
                    expected, Redirect,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                // Successfully redirected this cell.
                if (val != NullValue) {
                    // Copy the live value into the destination table.
                    bool ov = false;
                    Cell* dstCell = insertOrFind(key, dst, ov);
                    assert(dstCell != nullptr && !ov);
                    dstCell->value.store(val, std::memory_order_release);
                }
                break;
            }
            // CAS failed — another thread wrote a new value; retry.
        }
    }
}

// ============================================================
// Public API
// ============================================================

uint64_t ConcurrentHashMap::insert(uint64_t key, uint64_t value) {
    assert(key != NullKey);
    assert(value != NullValue && value != Redirect);

    for (;;) {
        Table* table = m_root.load(std::memory_order_acquire);

        // If a migration is already in progress, help complete it first.
        if (table->newTable.load(std::memory_order_acquire)) {
            helpMigrate(table);
            continue;  // Retry with the new root.
        }

        bool overflow = false;
        Cell* cell = insertOrFind(key, table, overflow);
        if (overflow) {
            beginMigration(table);
            continue;  // Retry in the larger table.
        }

        // CAS-loop to set the value, watching for Redirect.
        uint64_t oldVal = cell->value.load(std::memory_order_acquire);
        for (;;) {
            if (oldVal == Redirect) {
                // A migration redirected this cell while we were working.
                helpMigrate(table);
                break;  // Retry outer loop.
            }
            if (cell->value.compare_exchange_strong(
                    oldVal, value,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                // Successfully stored the value.
                //
                // Check if a concurrent migration started on this table
                // while we were inserting.  If newTable is non-null, a
                // migration is in progress (or finished).  Our cell may
                // have been skipped during the migration scan (it was
                // NullKey when migration read it, and we claimed it
                // afterwards).  Help complete the migration, then retry
                // the insert from the outer loop to guarantee the value
                // lands in the current root table.
                if (table->newTable.load(std::memory_order_acquire) != nullptr) {
                    helpMigrate(table);
                    break;  // Retry outer loop.
                }

                // No concurrent migration.  Check load factor.
                size_t pop = table->population.load(std::memory_order_relaxed);
                size_t cap = table->sizeMask + 1;
                if (pop * 4 > cap * 3) {  // > 75 %
                    beginMigration(table);
                }
                return oldVal;  // 0 if new insertion, old value if update.
            }
            // CAS failed; oldVal has been refreshed — retry inner loop.
        }
    }
}

uint64_t ConcurrentHashMap::get(uint64_t key) {
    assert(key != NullKey);

    for (;;) {
        Table* table = m_root.load(std::memory_order_acquire);
        Cell* cell = findCell(key, table);
        if (!cell) return NullValue;

        uint64_t val = cell->value.load(std::memory_order_acquire);
        if (val != Redirect) return val;

        // Cell was redirected — help finish the migration and retry.
        helpMigrate(table);
    }
}

uint64_t ConcurrentHashMap::erase(uint64_t key) {
    assert(key != NullKey);

    for (;;) {
        Table* table = m_root.load(std::memory_order_acquire);
        Cell* cell = findCell(key, table);
        if (!cell) return NullValue;

        uint64_t oldVal = cell->value.load(std::memory_order_acquire);
        for (;;) {
            if (oldVal == NullValue) return NullValue;
            if (oldVal == Redirect) {
                helpMigrate(table);
                break;  // Retry outer loop.
            }
            if (cell->value.compare_exchange_strong(
                    oldVal, NullValue,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return oldVal;
            }
            // CAS failed; oldVal refreshed — retry inner loop.
        }
    }
}
'''

os.makedirs('/app/src', exist_ok=True)
with open('/app/src/concurrent_hashmap.cpp', 'w') as f:
    f.write(IMPL.lstrip('\n'))

print("Implementation written to /app/src/concurrent_hashmap.cpp")

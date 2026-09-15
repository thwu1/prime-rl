#pragma once
//
// Lock-free Treiber stack with hazard-pointer-based memory reclamation.
// Memory ordering: acquire-release where safe, seq_cst where required
// by the hazard pointer protocol.

#include <atomic>
#include <cstddef>
#include <optional>
#include <stdexcept>
#include <thread>

template <typename T>
class LockFreeStack {
   private:
    struct Node {
        T data;
        Node* next;
        Node(T d) : data(std::move(d)), next(nullptr) {}
    };

    // ----------------------------------------------------------------
    // Hazard Pointer infrastructure
    // ----------------------------------------------------------------
    static constexpr std::size_t kMaxHazardPointers = 128;

    struct HazardSlot {
        std::atomic<std::thread::id> owner{};
        std::atomic<Node*> protected_ptr{nullptr};
    };

    // One global table per template instantiation (inline static = C++17).
    inline static HazardSlot hp_table_[kMaxHazardPointers]{};

    // RAII object: claims a slot on construction, releases on destruction.
    // Stored thread_local inside try_pop so each thread keeps its slot
    // for its entire lifetime.
    class HazardGuard {
        HazardSlot* slot_;

       public:
        HazardGuard() : slot_(nullptr) {
            auto tid = std::this_thread::get_id();
            for (std::size_t i = 0; i < kMaxHazardPointers; ++i) {
                std::thread::id nobody{};
                if (hp_table_[i].owner.compare_exchange_strong(
                        nobody, tid, std::memory_order_acq_rel,
                        std::memory_order_relaxed)) {
                    slot_ = &hp_table_[i];
                    return;
                }
            }
            throw std::runtime_error("All hazard pointer slots occupied");
        }
        HazardGuard(const HazardGuard&) = delete;
        HazardGuard& operator=(const HazardGuard&) = delete;

        std::atomic<Node*>& ref() { return slot_->protected_ptr; }

        ~HazardGuard() {
            // Clear pointer first so scanners stop seeing it, then release
            // the slot so a new thread can claim it.
            slot_->protected_ptr.store(nullptr, std::memory_order_release);
            slot_->owner.store(std::thread::id{}, std::memory_order_release);
        }
    };

    // Returns true if any hazard pointer currently protects `node`.
    static bool is_protected(Node* node) {
        for (std::size_t i = 0; i < kMaxHazardPointers; ++i) {
            if (hp_table_[i].protected_ptr.load(std::memory_order_acquire) ==
                node) {
                return true;
            }
        }
        return false;
    }

    // ----------------------------------------------------------------
    // Retire list  — lock-free singly-linked list of deferred deletions
    // ----------------------------------------------------------------
    struct RetiredNode {
        Node* node;
        RetiredNode* next;
        RetiredNode(Node* n) : node(n), next(nullptr) {}
    };

    std::atomic<RetiredNode*> retired_head_{nullptr};

    void retire(Node* node) {
        auto* rn = new RetiredNode(node);
        rn->next = retired_head_.load(std::memory_order_relaxed);
        while (!retired_head_.compare_exchange_weak(
            rn->next, rn, std::memory_order_release,
            std::memory_order_relaxed))
            ;
    }

    // Atomically claim the entire retire list, then walk it.
    // Delete nodes that are no longer protected; re-add the rest.
    void scan_and_reclaim() {
        RetiredNode* batch =
            retired_head_.exchange(nullptr, std::memory_order_acquire);
        while (batch) {
            RetiredNode* next = batch->next;
            if (!is_protected(batch->node)) {
                delete batch->node;
                delete batch;
            } else {
                // Still hazardous — put back on the retire list.
                batch->next = retired_head_.load(std::memory_order_relaxed);
                while (!retired_head_.compare_exchange_weak(
                    batch->next, batch, std::memory_order_release,
                    std::memory_order_relaxed))
                    ;
            }
            batch = next;
        }
    }

    // ----------------------------------------------------------------
    // Stack state
    // ----------------------------------------------------------------
    std::atomic<Node*> head_{nullptr};

   public:
    LockFreeStack() = default;
    LockFreeStack(const LockFreeStack&) = delete;
    LockFreeStack& operator=(const LockFreeStack&) = delete;

    void push(T val) {
        Node* node = new Node(std::move(val));
        node->next = head_.load(std::memory_order_relaxed);
        while (!head_.compare_exchange_weak(node->next, node,
                                            std::memory_order_release,
                                            std::memory_order_relaxed))
            ;
    }

    std::optional<T> try_pop() {
        // Each thread owns one hazard-pointer slot for its lifetime.
        thread_local HazardGuard guard;
        std::atomic<Node*>& hp = guard.ref();

        Node* old_head = head_.load(std::memory_order_acquire);
        do {
            // Inner loop: store the hazard pointer, then verify that head
            // has not changed.  The seq_cst store is essential — it
            // participates in a total order with the seq_cst fence in the
            // reclamation path, which prevents the TOCTOU race where a
            // reclaimer misses a concurrently published hazard pointer.
            Node* temp;
            do {
                temp = old_head;
                hp.store(old_head, std::memory_order_seq_cst);
                old_head = head_.load(std::memory_order_acquire);
            } while (old_head != temp);
            // After this loop: hp == old_head, and old_head was the value
            // of head at the time of the last load.  The node is now
            // protected — no reclaimer will free it.
        } while (old_head &&
                 !head_.compare_exchange_strong(old_head, old_head->next,
                                                std::memory_order_acq_rel,
                                                std::memory_order_acquire));

        // Clear the hazard pointer — we are done traversing old_head->next.
        hp.store(nullptr, std::memory_order_release);

        if (!old_head) return std::nullopt;

        T result = std::move(old_head->data);

        // A seq_cst fence before scanning ensures that our cleared HP is
        // visible AND that we see all other threads' HP stores before
        // deciding to delete.
        std::atomic_thread_fence(std::memory_order_seq_cst);

        if (is_protected(old_head)) {
            retire(old_head);
        } else {
            delete old_head;
        }

        scan_and_reclaim();
        return result;
    }

    T pop() {
        auto val = try_pop();
        if (!val) throw std::out_of_range("Stack is empty");
        return std::move(*val);
    }

    bool empty() const {
        return head_.load(std::memory_order_acquire) == nullptr;
    }

    ~LockFreeStack() {
        // Destruction is single-threaded — no concurrency concerns.
        Node* cur = head_.load(std::memory_order_relaxed);
        while (cur) {
            Node* nxt = cur->next;
            delete cur;
            cur = nxt;
        }
        RetiredNode* rn = retired_head_.load(std::memory_order_relaxed);
        while (rn) {
            RetiredNode* nxt = rn->next;
            delete rn->node;
            delete rn;
            rn = nxt;
        }
    }
};

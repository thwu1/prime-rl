#!/usr/bin/env python3
"""
Implement a complete hazard pointer memory reclamation system for the lock-free stack.

Creates memory_reclamation.hpp and modifies lockfree_stack.hpp to integrate it.
"""


def create_memory_reclamation():
    """Write the complete hazard pointer reclamation system."""
    code = r'''#ifndef MEMORY_RECLAMATION_HPP
#define MEMORY_RECLAMATION_HPP

#include <atomic>
#include <cstddef>
#include <stdexcept>
#include <thread>

constexpr std::size_t MaxHazardPointers = 128;

template <typename T>
struct HazardPointer {
    std::atomic<std::thread::id> id;
    std::atomic<Node<T>*> pointer{nullptr};
};

template <typename T>
HazardPointer<T> HazardPointers[MaxHazardPointers];

template <typename T>
class HazardPointerOwner {
    HazardPointer<T>* hazardPointer;

public:
    HazardPointerOwner(const HazardPointerOwner&) = delete;
    HazardPointerOwner& operator=(const HazardPointerOwner&) = delete;

    HazardPointerOwner() : hazardPointer(nullptr) {
        for (std::size_t i = 0; i < MaxHazardPointers; ++i) {
            std::thread::id old_id;
            if (HazardPointers<T>[i].id.compare_exchange_strong(
                    old_id, std::this_thread::get_id(),
                    std::memory_order_acquire, std::memory_order_relaxed)) {
                hazardPointer = &HazardPointers<T>[i];
                break;
            }
        }
        if (!hazardPointer) {
            throw std::out_of_range("No hazard pointers available!");
        }
    }

    std::atomic<Node<T>*>& getPointer() {
        return hazardPointer->pointer;
    }

    ~HazardPointerOwner() {
        // Clear the pointer before releasing the slot id.
        // If we cleared the id first, another thread could claim the slot
        // via CAS on the id and then have its hazard pointer overwritten
        // when we clear the pointer.
        hazardPointer->pointer.store(nullptr, std::memory_order_release);
        hazardPointer->id.store(std::thread::id(), std::memory_order_release);
    }
};

template <typename T>
std::atomic<Node<T>*>& getHazardPointer() {
    thread_local static HazardPointerOwner<T> hazard;
    return hazard.getPointer();
}

template <typename T>
class RetireList {
    struct RetiredNode {
        Node<T>* node;
        RetiredNode* next;
        RetiredNode(Node<T>* p) : node(p), next(nullptr) {}
        ~RetiredNode() { delete node; }
    };

    std::atomic<RetiredNode*> retiredNodes{nullptr};

    void addToRetiredNodes(RetiredNode* retiredNode) {
        retiredNode->next = retiredNodes.load(std::memory_order_relaxed);
        while (!retiredNodes.compare_exchange_weak(
            retiredNode->next, retiredNode,
            std::memory_order_release, std::memory_order_relaxed));
    }

public:
    bool isInUse(Node<T>* node) {
        for (std::size_t i = 0; i < MaxHazardPointers; ++i) {
            if (HazardPointers<T>[i].pointer.load(std::memory_order_acquire) == node) {
                return true;
            }
        }
        return false;
    }

    void addNode(Node<T>* node) {
        addToRetiredNodes(new RetiredNode(node));
    }

    void deleteUnusedNodes() {
        RetiredNode* current = retiredNodes.exchange(nullptr, std::memory_order_acquire);
        while (current) {
            RetiredNode* const next = current->next;
            if (!isInUse(current->node)) {
                delete current;  // ~RetiredNode cascade-deletes the Node
            } else {
                addToRetiredNodes(current);  // Still protected; re-retire
            }
            current = next;
        }
    }
};

#endif // MEMORY_RECLAMATION_HPP
'''
    with open("/app/memory_reclamation.hpp", "w") as f:
        f.write(code)
    print("Created /app/memory_reclamation.hpp")


def rewrite_lockfree_stack():
    """Rewrite lockfree_stack.hpp to integrate hazard pointer reclamation."""
    code = r'''#ifndef LOCKFREE_STACK_HPP
#define LOCKFREE_STACK_HPP

#include <atomic>
#include <stdexcept>
#include <thread>

template <typename T>
struct Node {
    T data;
    Node* next;
    Node(T d) : data(d), next(nullptr) {}
};

#include "memory_reclamation.hpp"

template <typename T>
class LockFreeStack {
    std::atomic<Node<T>*> head{nullptr};
    RetireList<T> retireList;

public:
    LockFreeStack() = default;
    LockFreeStack(const LockFreeStack&) = delete;
    LockFreeStack& operator=(const LockFreeStack&) = delete;

    void push(T val) {
        Node<T>* const newNode = new Node<T>(val);
        newNode->next = head.load(std::memory_order_relaxed);
        while (!head.compare_exchange_weak(newNode->next, newNode,
                std::memory_order_release, std::memory_order_relaxed));
    }

    T topAndPop() {
        std::atomic<Node<T>*>& hazardPointer = getHazardPointer<T>();
        Node<T>* oldHead = head.load(std::memory_order_relaxed);

        // Hazard pointer validation loop:
        // Publish HP to oldHead, then re-read head. If head changed,
        // the node we published might have been freed — retry.
        // The outer loop retries on CAS failure (another thread popped first).
        do {
            Node<T>* temp;
            do {
                temp = oldHead;
                hazardPointer.store(oldHead, std::memory_order_seq_cst);
                oldHead = head.load(std::memory_order_seq_cst);
            } while (oldHead != temp);
        } while (oldHead && !head.compare_exchange_strong(
            oldHead, oldHead->next,
            std::memory_order_acq_rel, std::memory_order_acquire));

        if (!oldHead) {
            hazardPointer.store(nullptr, std::memory_order_relaxed);
            throw std::out_of_range("The stack is empty!");
        }

        // Clear HP and extract data BEFORE retiring the node.
        // Once retired, another thread's deleteUnusedNodes may free it.
        hazardPointer.store(nullptr, std::memory_order_release);
        T result = oldHead->data;

        if (retireList.isInUse(oldHead)) {
            retireList.addNode(oldHead);
        } else {
            delete oldHead;
        }

        retireList.deleteUnusedNodes();

        return result;
    }

    ~LockFreeStack() {
        Node<T>* current = head.load();
        while (current) {
            Node<T>* next = current->next;
            delete current;
            current = next;
        }
    }
};

#endif // LOCKFREE_STACK_HPP
'''
    with open("/app/lockfree_stack.hpp", "w") as f:
        f.write(code)
    print("Rewrote /app/lockfree_stack.hpp with hazard pointer integration")


if __name__ == "__main__":
    create_memory_reclamation()
    rewrite_lockfree_stack()
    print("Hazard pointer reclamation system implemented successfully")

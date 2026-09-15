#ifndef LOCKFREE_STACK_HPP
#define LOCKFREE_STACK_HPP

#include <atomic>
#include <stdexcept>

template <typename T>
struct Node {
    T data;
    Node* next;
    Node(T d) : data(d), next(nullptr) {}
};

// Include your memory reclamation header here, after the Node definition.
// The reclamation system may reference Node<T>.
// #include "memory_reclamation.hpp"

template <typename T>
class LockFreeStack {
    std::atomic<Node<T>*> head{nullptr};

public:
    LockFreeStack() = default;
    LockFreeStack(const LockFreeStack&) = delete;
    LockFreeStack& operator=(const LockFreeStack&) = delete;

    void push(T val) {
        Node<T>* const newNode = new Node<T>(val);
        newNode->next = head.load();
        while (!head.compare_exchange_weak(newNode->next, newNode));
    }

    T topAndPop() {
        // This implementation correctly removes nodes from the stack using CAS,
        // but LEAKS every popped node. The naive approach of deleting the node
        // immediately after CAS causes use-after-free: between another thread's
        // head.load() and its read of head->next, the node may be freed.
        //
        // Without a safe reclamation scheme, we must leak to avoid undefined behavior.
        // Implement hazard pointer-based reclamation to safely free popped nodes.

        Node<T>* oldHead = head.load();
        while (oldHead && !head.compare_exchange_strong(oldHead, oldHead->next)) {
            // CAS failed: oldHead was updated by compare_exchange_strong to the
            // current value of head. Retry with the new value.
        }
        if (!oldHead) {
            throw std::out_of_range("The stack is empty!");
        }
        T result = oldHead->data;
        // LEAK: oldHead is never freed. Deleting it here would be unsafe
        // under concurrent access without a memory reclamation scheme.
        return result;
    }

    ~LockFreeStack() {
        // Clean up remaining nodes on the stack (only safe when no concurrent access).
        Node<T>* current = head.load();
        while (current) {
            Node<T>* next = current->next;
            delete current;
            current = next;
        }
    }
};

#endif // LOCKFREE_STACK_HPP

#pragma once
// Lock-free Treiber stack — no memory reclamation (leaks popped nodes)

#include <atomic>
#include <stdexcept>

template<typename T>
class LockFreeStack {
private:
    struct Node {
        T data;
        Node* next;
        Node(T d) : data(d), next(nullptr) {}
    };
    std::atomic<Node*> head{nullptr};

public:
    LockFreeStack() = default;
    LockFreeStack(const LockFreeStack&) = delete;
    LockFreeStack& operator=(const LockFreeStack&) = delete;

    void push(T val) {
        Node* newNode = new Node(val);
        newNode->next = head.load();
        while (!head.compare_exchange_strong(newNode->next, newNode));
    }

    T pop() {
        Node* oldHead = head.load();
        while (oldHead && !head.compare_exchange_strong(oldHead, oldHead->next));
        if (!oldHead) throw std::out_of_range("Stack is empty");
        T result = oldHead->data;
        // KNOWN ISSUE: cannot safely delete oldHead here because another
        // thread may still hold a pointer to it from a concurrent pop().
        // Deleting would cause use-after-free; not deleting leaks memory.
        return result;
    }

    bool empty() const {
        return head.load() == nullptr;
    }

    ~LockFreeStack() {
        Node* current = head.load();
        while (current) {
            Node* next = current->next;
            delete current;
            current = next;
        }
    }
};

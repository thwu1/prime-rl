//
// Single-threaded correctness tests for the lock-free stack.

#include "lockfree_stack.hpp"
#include <cassert>
#include <iostream>
#include <optional>
#include <stdexcept>

int main() {
    // Test 1: Basic LIFO push/pop
    {
        LockFreeStack<int> stack;
        stack.push(1);
        stack.push(2);
        stack.push(3);

        assert(stack.pop() == 3);
        assert(stack.pop() == 2);
        assert(stack.pop() == 1);
        std::cout << "BASIC_PUSH_POP_PASSED" << std::endl;
    }

    // Test 2: try_pop on empty stack returns nullopt
    {
        LockFreeStack<int> stack;
        auto result = stack.try_pop();
        assert(!result.has_value());
        std::cout << "TRY_POP_EMPTY_PASSED" << std::endl;
    }

    // Test 3: try_pop on non-empty stack returns value
    {
        LockFreeStack<int> stack;
        stack.push(42);
        auto result = stack.try_pop();
        assert(result.has_value());
        assert(*result == 42);
        result = stack.try_pop();
        assert(!result.has_value());
        std::cout << "TRY_POP_NONEMPTY_PASSED" << std::endl;
    }

    // Test 4: pop on empty stack throws std::out_of_range
    {
        LockFreeStack<int> stack;
        bool caught = false;
        try {
            stack.pop();
        } catch (const std::out_of_range&) {
            caught = true;
        }
        assert(caught);
        std::cout << "POP_EMPTY_THROWS_PASSED" << std::endl;
    }

    // Test 5: Large sequential push/pop
    {
        LockFreeStack<int> stack;
        const int N = 10000;
        for (int i = 0; i < N; i++) stack.push(i);
        for (int i = N - 1; i >= 0; i--) {
            assert(stack.pop() == i);
        }
        std::cout << "LARGE_SEQUENTIAL_PASSED" << std::endl;
    }

    // Test 6: empty() method
    {
        LockFreeStack<int> stack;
        assert(stack.empty());
        stack.push(1);
        assert(!stack.empty());
        stack.pop();
        assert(stack.empty());
        std::cout << "EMPTY_METHOD_PASSED" << std::endl;
    }

    std::cout << "ALL_BASIC_TESTS_PASSED" << std::endl;
    return 0;
}

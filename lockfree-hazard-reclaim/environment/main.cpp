// Smoke test for the lock-free stack
#include "lockfree_stack.hpp"
#include <iostream>
#include <future>

int main() {
    LockFreeStack<int> stack;

    auto f1 = std::async(std::launch::async, [&]{ stack.push(10); });
    auto f2 = std::async(std::launch::async, [&]{ stack.push(20); });
    auto f3 = std::async(std::launch::async, [&]{ stack.push(30); });

    f1.get(); f2.get(); f3.get();

    auto f4 = std::async(std::launch::async, [&]{ return stack.pop(); });
    auto f5 = std::async(std::launch::async, [&]{ return stack.pop(); });
    auto f6 = std::async(std::launch::async, [&]{ return stack.pop(); });

    std::cout << f4.get() << '\n';
    std::cout << f5.get() << '\n';
    std::cout << f6.get() << '\n';

    return 0;
}

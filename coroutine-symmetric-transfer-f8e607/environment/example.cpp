// example.cpp — Intended usage of the coroutine library.
// This should compile and run correctly after all defects are fixed
// and all stubs are implemented.

#include "coro/task.hpp"
#include "coro/sync_wait.hpp"
#include "coro/generator.hpp"
#include "coro/when_all.hpp"
#include <cstdio>
#include <tuple>
#include <string>

coro::task<int> add(int a, int b) {
    co_return a + b;
}

coro::task<int> compute() {
    int x = co_await add(3, 4);
    int y = co_await add(x, 10);
    co_return y;
}

coro::generator<int> iota(int n) {
    for (int i = 0; i < n; ++i) {
        co_yield i;
    }
}

int main() {
    // sync_wait drives a task graph to completion
    int result = coro::sync_wait(compute());
    printf("compute: %d\n", result);

    // generator yields values lazily
    int gen_sum = 0;
    for (int v : iota(5)) {
        gen_sum += v;
    }
    printf("gen_sum: %d\n", gen_sum);

    // when_all composes multiple tasks
    auto [a, b] = coro::sync_wait(
        coro::when_all(add(10, 20), add(30, 40))
    );
    printf("when_all: %d, %d\n", a, b);

    return (result == 17 && gen_sum == 10 && a == 30 && b == 70) ? 0 : 1;
}

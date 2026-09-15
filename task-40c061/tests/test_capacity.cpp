
#include "/app/spsc_queue.hpp"
#include <cstdio>
#include <cstdlib>

int main() {
    constexpr int CAP = 100;
    SPSCQueue<int> q(CAP);

    // Phase 1: Push exactly CAP items — all must succeed
    for (int i = 0; i < CAP; ++i) {
        if (!q.push(i)) {
            printf("FAIL: push failed at index %d, expected capacity %d\n", i, CAP);
            return 1;
        }
    }

    // Phase 2: The (CAP+1)-th push must fail (queue is full)
    if (q.push(CAP)) {
        printf("FAIL: push beyond capacity %d succeeded\n", CAP);
        return 1;
    }

    // Phase 3: Consume all items and verify count
    int count = 0;
    while (q.consume_one([&](int&) { count++; }));

    if (count != CAP) {
        printf("FAIL: consumed %d items, expected %d\n", count, CAP);
        return 1;
    }

    // Phase 4: Verify queue is now empty
    bool got = q.consume_one([](int&) {});
    if (got) {
        printf("FAIL: queue not empty after consuming all items\n");
        return 1;
    }

    printf("PASS\n");
    return 0;
}

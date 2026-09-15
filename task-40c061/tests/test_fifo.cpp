
#include "/app/spsc_queue.hpp"
#include <cstdio>
#include <cstdlib>

int main() {
    // Test 1: Basic FIFO order
    {
        SPSCQueue<int> q(16);
        for (int i = 0; i < 5; ++i) {
            if (!q.push(i)) {
                printf("FAIL: basic push %d failed\n", i);
                return 1;
            }
        }
        for (int i = 0; i < 5; ++i) {
            int got = -1;
            bool ok = q.consume_one([&](int& v) { got = v; });
            if (!ok || got != i) {
                printf("FAIL: basic FIFO expected %d, got %d (ok=%d)\n", i, got, ok);
                return 1;
            }
        }
    }

    // Test 2: Interleaved push and consume
    {
        SPSCQueue<int> q(16);
        q.push(10);
        q.push(20);

        int v = -1;
        q.consume_one([&](int& x) { v = x; });
        if (v != 10) {
            printf("FAIL: interleaved first consume expected 10, got %d\n", v);
            return 1;
        }

        q.push(30);
        q.push(40);

        int expected[] = {20, 30, 40};
        for (int i = 0; i < 3; ++i) {
            int got = -1;
            bool ok = q.consume_one([&](int& x) { got = x; });
            if (!ok || got != expected[i]) {
                printf("FAIL: interleaved at %d expected %d, got %d (ok=%d)\n",
                       i, expected[i], got, ok);
                return 1;
            }
        }
    }

    // Test 3: Wrap-around FIFO — fill and drain multiple times to force index wrapping
    {
        SPSCQueue<int> q(8);
        for (int round = 0; round < 20; ++round) {
            for (int i = 0; i < 5; ++i) {
                if (!q.push(round * 100 + i)) {
                    printf("FAIL: wrap push failed round=%d i=%d\n", round, i);
                    return 1;
                }
            }
            for (int i = 0; i < 5; ++i) {
                int got = -1;
                int expected = round * 100 + i;
                bool ok = q.consume_one([&](int& x) { got = x; });
                if (!ok || got != expected) {
                    printf("FAIL: wrap round=%d i=%d expected=%d got=%d\n",
                           round, i, expected, got);
                    return 1;
                }
            }
        }
    }

    // Test 4: Single-element queue (capacity 1)
    {
        SPSCQueue<int> q(1);
        if (!q.push(42)) {
            printf("FAIL: single-element push failed\n");
            return 1;
        }
        if (q.push(99)) {
            printf("FAIL: single-element queue accepted second push\n");
            return 1;
        }
        int got = -1;
        q.consume_one([&](int& x) { got = x; });
        if (got != 42) {
            printf("FAIL: single-element expected 42, got %d\n", got);
            return 1;
        }
    }

    printf("PASS\n");
    return 0;
}

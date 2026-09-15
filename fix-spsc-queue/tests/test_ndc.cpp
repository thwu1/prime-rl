
// Verifies that the queue works with types that have no default constructor.
// This exercises the placement-new (construct_at) storage approach.

#include "spsc_queue.hpp"
#include <cstdlib>
#include <iostream>
#include <string>

struct Order {
    int id;
    double price;
    int quantity;
    std::string symbol;

    Order(int id_, double price_, int qty_, const char* sym_)
        : id(id_), price(price_), quantity(qty_), symbol(sym_) {}

    // Explicitly delete default constructor
    Order() = delete;
};

int main() {
    SPSCQueue<Order> q(100);

    // Push 100 orders
    for (int i = 0; i < 100; ++i) {
        Order o(i, 100.0 + i * 0.25, (i + 1) * 10, "AAPL");
        if (!q.push(o)) {
            std::cerr << "FAIL: push failed at " << i << "\n";
            return 1;
        }
    }

    // Queue should be full
    Order extra(999, 0.0, 0, "X");
    if (q.push(extra)) {
        std::cerr << "FAIL: push should fail on full queue\n";
        return 1;
    }

    // Pop and verify
    for (int i = 0; i < 100; ++i) {
        bool ok = q.consume_one([&](Order& o) {
            if (o.id != i) {
                std::cerr << "FAIL: expected id " << i << " got " << o.id
                          << "\n";
                std::exit(1);
            }
            if (o.quantity != (i + 1) * 10) {
                std::cerr << "FAIL: quantity mismatch at " << i << "\n";
                std::exit(1);
            }
            if (o.symbol != "AAPL") {
                std::cerr << "FAIL: symbol mismatch at " << i << "\n";
                std::exit(1);
            }
        });
        if (!ok) {
            std::cerr << "FAIL: consume_one returned false at " << i << "\n";
            return 1;
        }
    }

    // Queue should be empty
    if (q.consume_one([](Order&) {})) {
        std::cerr << "FAIL: queue should be empty\n";
        return 1;
    }

    std::cout << "PASS: non-default-constructible type (Order)\n";
    return 0;
}

#!/usr/bin/env python3
"""Generate a deterministic rooted tree in SQLite for the skiptree task."""
import sqlite3
import random


def main():
    random.seed(42)
    conn = sqlite3.connect('/app/tree.db')
    c = conn.cursor()
    c.execute('CREATE TABLE tree (id INTEGER PRIMARY KEY, parent_id INTEGER)')

    N = 10000

    # Root node
    c.execute('INSERT INTO tree VALUES (0, NULL)')

    # Backbone chain: ensures depth >= 60
    for i in range(1, 61):
        c.execute('INSERT INTO tree VALUES (?, ?)', (i, i - 1))

    # Remaining nodes: mix of deep attachment (extends chains) and random
    node_list = list(range(61))
    for i in range(61, N):
        if random.random() < 0.3:
            # Attach to a recent node to create deeper chains
            window = min(20, len(node_list))
            parent = node_list[len(node_list) - random.randint(1, window)]
        else:
            # Attach to any existing node for breadth
            parent = node_list[random.randint(0, len(node_list) - 1)]
        c.execute('INSERT INTO tree VALUES (?, ?)', (i, parent))
        node_list.append(i)

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()

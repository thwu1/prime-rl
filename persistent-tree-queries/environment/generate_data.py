import random
import sqlite3
import os


def main():
    random.seed(314159265)
    N = 100000
    M = 100000
    K = 100000

    # Generate tree structure
    parents = [0] * (N + 1)
    for i in range(2, 501):
        parents[i] = i - 1
    parents[501] = 250
    for i in range(502, 1001):
        parents[i] = i - 1
    for i in range(1001, N + 1):
        parents[i] = random.randint(1, i - 1)

    values = [random.randint(1, 10**9) for _ in range(N)]

    updates = []
    for _ in range(M):
        node = random.randint(1, N)
        val = random.randint(1, 10**9)
        updates.append((node, val))

    queries = []
    for _ in range(K):
        version = random.randint(0, M)
        u = random.randint(1, N)
        w = random.randint(1, N)
        queries.append((version, u, w))

    # Create SQLite database
    os.makedirs('/app/data', exist_ok=True)
    conn = sqlite3.connect('/app/data/tree.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE nd (
        nid INTEGER PRIMARY KEY,
        pid INTEGER,
        bval INTEGER NOT NULL
    )''')
    c.execute('''CREATE TABLE mods (
        mid INTEGER PRIMARY KEY AUTOINCREMENT,
        tgt INTEGER NOT NULL,
        nval INTEGER NOT NULL
    )''')
    c.execute('''CREATE TABLE pq (
        qid INTEGER PRIMARY KEY AUTOINCREMENT,
        ver INTEGER NOT NULL,
        ea INTEGER NOT NULL,
        eb INTEGER NOT NULL
    )''')
    c.execute('''CREATE TABLE meta (
        key TEXT PRIMARY KEY,
        info TEXT NOT NULL
    )''')

    # Insert root (pid = NULL)
    c.execute('INSERT INTO nd VALUES (1, NULL, ?)', (values[0],))
    for i in range(2, N + 1):
        c.execute('INSERT INTO nd VALUES (?, ?, ?)', (i, parents[i], values[i - 1]))

    c.executemany('INSERT INTO mods (tgt, nval) VALUES (?, ?)', updates)
    c.executemany('INSERT INTO pq (ver, ea, eb) VALUES (?, ?, ?)', queries)

    c.execute("INSERT INTO meta VALUES ('structure', 'rooted_tree')")
    c.execute("INSERT INTO meta VALUES ('root', '1')")
    c.execute("INSERT INTO meta VALUES ('versioning', 'sequential_cumulative')")
    c.execute("INSERT INTO meta VALUES ('aggregation', 'path_sum_inclusive')")

    conn.commit()
    conn.close()


main()

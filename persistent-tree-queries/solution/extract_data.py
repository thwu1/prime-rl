
import sqlite3


def main():
    conn = sqlite3.connect('/app/data/tree.db')
    c = conn.cursor()

    nodes = list(c.execute('SELECT nid, pid, bval FROM nd ORDER BY nid'))
    N = len(nodes)

    mods = list(c.execute('SELECT tgt, nval FROM mods ORDER BY mid'))
    M = len(mods)

    queries = list(c.execute('SELECT ver, ea, eb FROM pq ORDER BY qid'))
    K = len(queries)

    with open('/solution/input.txt', 'w') as f:
        f.write(f"{N} {M} {K}\n")
        f.write(' '.join(str(pid) for nid, pid, bval in nodes if nid > 1) + '\n')
        f.write(' '.join(str(bval) for nid, pid, bval in nodes) + '\n')
        for tgt, nval in mods:
            f.write(f"U {tgt} {nval}\n")
        for ver, ea, eb in queries:
            f.write(f"Q {ver} {ea} {eb}\n")

    conn.close()


main()

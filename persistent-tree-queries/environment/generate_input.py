import random

def main():
    random.seed(314159265)
    N = 100000
    M = 100000
    K = 100000

    parent = [0] * (N + 1)
    # Chain segment for interesting deep paths
    for i in range(2, 501):
        parent[i] = i - 1
    # Branch from node 250
    parent[501] = 250
    for i in range(502, 1001):
        parent[i] = i - 1
    # Rest: random parents
    for i in range(1001, N + 1):
        parent[i] = random.randint(1, i - 1)

    values = [random.randint(1, 10**9) for _ in range(N)]

    with open('/app/data/input.txt', 'w') as f:
        f.write(f"{N} {M} {K}\n")
        f.write(' '.join(str(parent[i]) for i in range(2, N + 1)) + '\n')
        f.write(' '.join(str(v) for v in values) + '\n')

        for _ in range(M):
            node = random.randint(1, N)
            val = random.randint(1, 10**9)
            f.write(f"U {node} {val}\n")

        for _ in range(K):
            version = random.randint(0, M)
            u = random.randint(1, N)
            w = random.randint(1, N)
            f.write(f"Q {version} {u} {w}\n")

main()

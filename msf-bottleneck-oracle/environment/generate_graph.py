import random

random.seed(15210)

N = 5000
comp_sizes = [1300, 1250, 1200, 1250]
assert sum(comp_sizes) == N

components = []
start = 0
for size in comp_sizes:
    components.append(list(range(start, start + size)))
    start += size

edges = []
edge_set = set()

for comp in components:
    perm = comp.copy()
    random.shuffle(perm)
    for i in range(1, len(perm)):
        u, v = min(perm[i - 1], perm[i]), max(perm[i - 1], perm[i])
        edge_set.add((u, v))
        edges.append((u, v))

    extra_target = len(comp) * 4
    added = 0
    while added < extra_target:
        u = random.choice(comp)
        v = random.choice(comp)
        if u == v:
            continue
        key = (min(u, v), max(u, v))
        if key in edge_set:
            continue
        edge_set.add(key)
        edges.append(key)
        added += 1

M = len(edges)
weights = random.sample(range(1, 10_000_000), M)

indexed = sorted([(u, v, w) for (u, v), w in zip(edges, weights)])

with open('/app/graph.txt', 'w') as f:
    f.write(f"{N} {M}\n")
    for u, v, w in indexed:
        f.write(f"{u} {v} {w}\n")

queries = []
for _ in range(6500):
    ci = random.randint(0, len(components) - 1)
    comp = components[ci]
    u = random.choice(comp)
    v = random.choice(comp)
    while u == v:
        v = random.choice(comp)
    queries.append((u, v))

for _ in range(1500):
    ci = random.randint(0, len(components) - 1)
    cj = random.randint(0, len(components) - 1)
    while ci == cj:
        cj = random.randint(0, len(components) - 1)
    u = random.choice(components[ci])
    v = random.choice(components[cj])
    queries.append((u, v))

random.shuffle(queries)

with open('/app/queries.txt', 'w') as f:
    f.write(f"{len(queries)}\n")
    for u, v in queries:
        f.write(f"{u} {v}\n")

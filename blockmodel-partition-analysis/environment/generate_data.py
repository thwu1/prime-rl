#!/usr/bin/env python3
"""Generate synthetic directed blockmodel graph and candidate partitions."""
import random
import os

random.seed(42)

N = 200
K = 5

# Assign nodes to blocks deterministically (round-robin)
true_partition = [i % K for i in range(N)]

# Generate directed edges according to planted partition model
p_within = 0.15
p_between = 0.01

os.makedirs('/app/candidate_partitions', exist_ok=True)

edges = []
for i in range(N):
    for j in range(N):
        if i == j:
            continue
        p = p_within if true_partition[i] == true_partition[j] else p_between
        if random.random() < p:
            edges.append((i + 1, j + 1, 1))

# Write graph edge list (1-indexed: source, destination, weight)
with open('/app/graph.tsv', 'w') as f:
    for src, dst, w in edges:
        f.write('{}\t{}\t{}\n'.format(src, dst, w))

# Write truth partition (1-indexed: node, block)
with open('/app/truth_partition.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, true_partition[i] + 1))

# Candidate 1: Random assignment to 5 blocks
with open('/app/candidate_partitions/partition_1.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, random.randint(1, K)))

# Candidate 2: All nodes in one block (trivial partition, B=1)
with open('/app/candidate_partitions/partition_2.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t1\n'.format(i + 1))

# Candidate 3: Random assignment to 8 blocks (over-partitioned)
with open('/app/candidate_partitions/partition_3.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, random.randint(1, 8)))

# Candidate 4: Noisy truth (~70% correct, 5 blocks)
c4 = list(true_partition)
for i in range(N):
    if random.random() < 0.3:
        c4[i] = random.randint(0, K - 1)
with open('/app/candidate_partitions/partition_4.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, c4[i] + 1))

# Candidate 5: Good partition (~90% correct, 5 blocks)
c5 = list(true_partition)
for i in range(N):
    if random.random() < 0.1:
        c5[i] = random.randint(0, K - 1)
with open('/app/candidate_partitions/partition_5.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, c5[i] + 1))

# Candidate 6: Near-perfect partition (~98% correct, 5 blocks)
c6 = list(true_partition)
for i in range(N):
    if random.random() < 0.02:
        c6[i] = random.randint(0, K - 1)
with open('/app/candidate_partitions/partition_6.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, c6[i] + 1))

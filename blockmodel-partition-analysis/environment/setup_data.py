#!/usr/bin/env python3
"""Generate synthetic directed blockmodel graph and candidate partitions."""
import random
import os

random.seed(42)

N = 200
K = 5

true_partition = [i % K for i in range(N)]

p_within = 0.15
p_between = 0.01

os.makedirs('/app/data/detections', exist_ok=True)
os.makedirs('/app/pipeline', exist_ok=True)

edges = []
for i in range(N):
    for j in range(N):
        if i == j:
            continue
        p = p_within if true_partition[i] == true_partition[j] else p_between
        if random.random() < p:
            edges.append((i + 1, j + 1, 1))

with open('/app/data/network.tsv', 'w') as f:
    for src, dst, w in edges:
        f.write('{}\t{}\t{}\n'.format(src, dst, w))

with open('/app/data/ground_truth.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, true_partition[i] + 1))

# A: Random assignment to 5 blocks
with open('/app/data/detections/result_A.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, random.randint(1, K)))

# B: All nodes in one block
with open('/app/data/detections/result_B.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t1\n'.format(i + 1))

# C: Over-partitioned (8 blocks)
with open('/app/data/detections/result_C.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, random.randint(1, 8)))

# D: Noisy truth (~70% correct)
c4 = list(true_partition)
for i in range(N):
    if random.random() < 0.3:
        c4[i] = random.randint(0, K - 1)
with open('/app/data/detections/result_D.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, c4[i] + 1))

# E: Good partition (~90% correct)
c5 = list(true_partition)
for i in range(N):
    if random.random() < 0.1:
        c5[i] = random.randint(0, K - 1)
with open('/app/data/detections/result_E.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, c5[i] + 1))

# F: Near-perfect partition (~98% correct)
c6 = list(true_partition)
for i in range(N):
    if random.random() < 0.02:
        c6[i] = random.randint(0, K - 1)
with open('/app/data/detections/result_F.tsv', 'w') as f:
    for i in range(N):
        f.write('{}\t{}\n'.format(i + 1, c6[i] + 1))

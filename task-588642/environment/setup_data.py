#!/usr/bin/env python3
"""Generate dictionary and queries for the parametric Levenshtein DFA task."""


import json
import random
import string

random.seed(73421)

consonants = list('bcdfghjklmnpqrstvwxyz')
vowels = list('aeiou')

words = set()

# Type 1: CV-alternating words (natural sounding)
for _ in range(15000):
    length = random.randint(3, 10)
    word = []
    for i in range(length):
        if i % 2 == 0:
            word.append(random.choice(consonants))
        else:
            word.append(random.choice(vowels))
    words.add(''.join(word))

# Type 2: Semi-random lowercase words
for _ in range(8000):
    length = random.randint(3, 8)
    word = ''.join(random.choice(string.ascii_lowercase) for _ in range(length))
    words.add(word)

words = sorted(words)

# Write dictionary
with open('/app/dictionary.txt', 'w') as f:
    for w in words:
        f.write(w + '\n')

# Generate queries
random.seed(99887)
queries = []

# Pick some dictionary words (will find themselves + neighbors)
sample = random.sample(words, 6)
for w in sample:
    queries.append({"query": w, "max_distance": 2})

# Pick some and modify by 1-2 edits
sample2 = random.sample(words, 5)
for w in sample2:
    w_list = list(w)
    pos = random.randint(0, len(w_list) - 1)
    w_list[pos] = random.choice(string.ascii_lowercase)
    queries.append({"query": ''.join(w_list), "max_distance": 2})

# Some with distance 1
sample3 = random.sample(words, 2)
for w in sample3:
    queries.append({"query": w, "max_distance": 1})

# Edge cases
queries.append({"query": "a", "max_distance": 1})
queries.append({"query": "xyz", "max_distance": 2})

with open('/app/queries.json', 'w') as f:
    json.dump(queries, f, indent=2)

print(f"Generated {len(words)} dictionary words and {len(queries)} queries")

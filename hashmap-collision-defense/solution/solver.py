"""
Solver for the hash-table collision attack and defense task.

Part 1 — Attack:
  The hash function is  h(key) = (key * MULT) >> 48  (top 16 bits of product).
  MULT = 0x517cc1b727220a95 is odd, so it has a multiplicative inverse mod 2^64.
  For any v < 2^48, the key  k = v * INV mod 2^64  satisfies
      h(k) = (v * INV * MULT) >> 48 = v >> 48 = 0.
  So keys {1*INV, 2*INV, …, N*INV} all hash to bucket 0.

Part 2 — Defense:
  Add a per-table random seed (set in ht_init from /dev/urandom).
  Replace the bare multiply-shift with  XOR-seed then splitmix64 finalizer,
  which is a bijection with excellent avalanche.  An attacker who does not
  know the seed cannot predict bucket assignments.
"""

import os
import subprocess

# ── constants ────────────────────────────────────────────────────────────────

HASH_MULT = 0x517cc1b727220a95
MOD = 1 << 64
NUM_KEYS = 12_000          # generate a bit more than the 10 000 minimum
TABLE_BITS = 16

# ── Part 1: generate adversarial keys ────────────────────────────────────────

def modinv_pow2(a, k):
    """Modular inverse of odd *a* modulo 2**k via Newton iteration."""
    assert a & 1, "a must be odd"
    m = 1 << k
    x = a          # a * a ≡ a² ≡ 1  (mod 2) when a is odd — close enough
    for _ in range(k.bit_length() + 1):      # converges in ≤ ceil(log2(k))+1 steps
        x = (x * (2 - a * x)) % m
    assert (a * x) % m == 1
    return x

inv = modinv_pow2(HASH_MULT, 64)

keys = [(v * inv) % MOD for v in range(1, NUM_KEYS + 1)]

# sanity-check: every key should hash to bucket 0
for k in keys:
    assert ((k * HASH_MULT) % MOD) >> (64 - TABLE_BITS) == 0

# Ensure /app directory structure exists (runtime may mount a fresh volume)
os.makedirs("/app/src", exist_ok=True)

with open("/app/adversarial_input.txt", "w") as f:
    for k in keys:
        f.write(f"{k}\n")

print(f"[+] Wrote {len(keys)} adversarial keys to /app/adversarial_input.txt")

# ── Part 2: patch hashtable.h / hashtable.c ──────────────────────────────────

PATCHED_H = """\
#ifndef HASHTABLE_H
#define HASHTABLE_H

#include <stdint.h>
#include <stddef.h>

#define TABLE_BITS 16
#define TABLE_SIZE (1 << TABLE_BITS)
#define TABLE_MASK (TABLE_SIZE - 1)

typedef struct {
    uint64_t key;
    uint64_t value;
    uint8_t occupied;
} Entry;

typedef struct {
    Entry entries[TABLE_SIZE];
    size_t count;
    uint64_t seed;
} HashTable;

void ht_init(HashTable* ht);
int ht_insert(HashTable* ht, uint64_t key, uint64_t value);
int ht_lookup(const HashTable* ht, uint64_t key, uint64_t* value);
int ht_delete(HashTable* ht, uint64_t key);

#endif
"""

PATCHED_C = """\
#include "hashtable.h"
#include <string.h>
#include <fcntl.h>
#include <unistd.h>

static uint64_t random_seed(void) {
    uint64_t s = 0;
    int fd = open("/dev/urandom", O_RDONLY);
    if (fd >= 0) {
        if (read(fd, &s, sizeof(s)) < 0)
            s = (uint64_t)(uintptr_t)&s ^ 0xdeadbeefcafebabeULL;
        close(fd);
    } else {
        s = (uint64_t)(uintptr_t)&s ^ 0xdeadbeefcafebabeULL;
    }
    return s;
}

/* Keyed hash: XOR with per-table seed, then splitmix64 finalizer. */
static uint32_t hash_key(uint64_t key, uint64_t seed) {
    uint64_t h = key ^ seed;
    h ^= h >> 30;
    h *= 0xbf58476d1ce4e5b9ULL;
    h ^= h >> 27;
    h *= 0x94d049bb133111ebULL;
    h ^= h >> 31;
    return (uint32_t)(h >> (64 - TABLE_BITS));
}

void ht_init(HashTable* ht) {
    memset(ht, 0, sizeof(HashTable));
    ht->seed = random_seed();
}

int ht_insert(HashTable* ht, uint64_t key, uint64_t value) {
    if (ht->count >= TABLE_SIZE * 3 / 4)
        return -1;
    uint32_t idx = hash_key(key, ht->seed);
    for (;;) {
        uint32_t i = idx & TABLE_MASK;
        if (!ht->entries[i].occupied) {
            ht->entries[i].key = key;
            ht->entries[i].value = value;
            ht->entries[i].occupied = 1;
            ht->count++;
            return 0;
        }
        if (ht->entries[i].key == key) {
            ht->entries[i].value = value;
            return 0;
        }
        idx++;
    }
}

int ht_lookup(const HashTable* ht, uint64_t key, uint64_t* value) {
    uint32_t idx = hash_key(key, ht->seed);
    for (;;) {
        uint32_t i = idx & TABLE_MASK;
        if (!ht->entries[i].occupied)
            return 0;
        if (ht->entries[i].key == key) {
            if (value) *value = ht->entries[i].value;
            return 1;
        }
        idx++;
    }
}

int ht_delete(HashTable* ht, uint64_t key) {
    uint32_t idx = hash_key(key, ht->seed);
    for (;;) {
        uint32_t i = idx & TABLE_MASK;
        if (!ht->entries[i].occupied)
            return 0;
        if (ht->entries[i].key == key) {
            ht->entries[i].occupied = 0;
            ht->count--;
            /* backward-shift to maintain linear-probing chains */
            uint32_t j = (i + 1) & TABLE_MASK;
            while (ht->entries[j].occupied) {
                uint32_t natural = hash_key(ht->entries[j].key, ht->seed)
                                   & TABLE_MASK;
                int should_move;
                if (i <= j)
                    should_move = (natural <= i) || (natural > j);
                else
                    should_move = (natural <= i) && (natural > j);
                if (should_move) {
                    ht->entries[i] = ht->entries[j];
                    ht->entries[j].occupied = 0;
                    i = j;
                }
                j = (j + 1) & TABLE_MASK;
            }
            return 1;
        }
        idx++;
    }
}
"""

MAIN_C = """\
#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
#include <time.h>
#include "hashtable.h"

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <input_file>\\n", argv[0]);
        return 1;
    }

    FILE* f = fopen(argv[1], "r");
    if (!f) {
        perror("fopen");
        return 1;
    }

    HashTable* ht = calloc(1, sizeof(HashTable));
    if (!ht) {
        fprintf(stderr, "Failed to allocate hash table\\n");
        return 1;
    }
    ht_init(ht);

    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);

    uint64_t key;
    int count = 0;
    while (fscanf(f, "%" SCNu64, &key) == 1) {
        if (ht_insert(ht, key, key) != 0) break;
        count++;
    }

    clock_gettime(CLOCK_MONOTONIC, &end);

    double elapsed = (end.tv_sec - start.tv_sec) +
                     (end.tv_nsec - start.tv_nsec) / 1e9;
    printf("Inserted %d keys in %.6f seconds\\n", count, elapsed);

    rewind(f);
    int found = 0;
    while (fscanf(f, "%" SCNu64, &key) == 1 && found < count) {
        uint64_t val;
        if (ht_lookup(ht, key, &val) && val == key) found++;
    }
    printf("Verified %d/%d lookups\\n", found, count);

    fclose(f);
    free(ht);
    return 0;
}
"""

# Write all source files to /app — handles the case where runtime mounts
# a fresh /app volume that shadows the Docker image contents.

with open("/app/src/hashtable.h", "w") as f:
    f.write(PATCHED_H)
with open("/app/src/hashtable.c", "w") as f:
    f.write(PATCHED_C)
with open("/app/src/main.c", "w") as f:
    f.write(MAIN_C)

# Write Makefile with proper tab indentation for recipes
with open("/app/Makefile", "w") as f:
    f.write("CC = gcc\n")
    f.write("CFLAGS = -O2 -Wall -Wextra\n")
    f.write("\n")
    f.write("all: kvstore\n")
    f.write("\n")
    f.write("kvstore: src/main.c src/hashtable.c src/hashtable.h\n")
    f.write("\t$(CC) $(CFLAGS) -o $@ src/main.c src/hashtable.c -Isrc\n")
    f.write("\n")
    f.write("clean:\n")
    f.write("\trm -f kvstore\n")
    f.write("\n")
    f.write(".PHONY: all clean\n")

print("[+] Patched hashtable.h and hashtable.c with keyed splitmix64 hash")

# ── verify compilation ───────────────────────────────────────────────────────

r = subprocess.run(["make", "-C", "/app", "clean"], capture_output=True)
r = subprocess.run(["make", "-C", "/app"], capture_output=True)
assert r.returncode == 0, (
    f"Compilation failed:\nstdout: {r.stdout.decode()}\nstderr: {r.stderr.decode()}"
)
print("[+] Modified code compiles successfully")

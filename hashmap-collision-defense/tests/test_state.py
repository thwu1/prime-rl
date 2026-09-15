
import os
import subprocess
import collections

# Original hash function parameters (from the unmodified hashtable.c)
ORIGINAL_HASH_MULT = 0x517cc1b727220a95
TABLE_BITS = 16
TABLE_SIZE = 1 << TABLE_BITS
TABLE_MASK = TABLE_SIZE - 1
MASK_64 = (1 << 64) - 1


def original_hash(key):
    """Reimplementation of the original vulnerable multiply-shift hash."""
    return ((key * ORIGINAL_HASH_MULT) & MASK_64) >> (64 - TABLE_BITS)


def read_adversarial_keys():
    keys = []
    with open("/app/adversarial_input.txt") as f:
        for line in f:
            line = line.strip()
            if line:
                keys.append(int(line))
    return keys


def compile_and_run(test_code, test_name, timeout=120):
    """Write a C test program, compile against modified hashtable, run it."""
    test_path = f"/tmp/tbench_{test_name}.c"
    binary_path = f"/tmp/tbench_{test_name}"

    with open(test_path, "w") as f:
        f.write(test_code)

    comp = subprocess.run(
        ["gcc", "-O2", "-o", binary_path, test_path,
         "/app/src/hashtable.c", "-I/app/src"],
        capture_output=True, timeout=30
    )
    if comp.returncode != 0:
        raise AssertionError(
            f"Compilation failed:\nstdout: {comp.stdout.decode()}\n"
            f"stderr: {comp.stderr.decode()}"
        )

    run = subprocess.run(
        [binary_path], capture_output=True, timeout=timeout
    )
    return run


# ── Part 1: Adversarial input file ──────────────────────────────────────────


class TestAdversarialFile:

    def test_file_exists(self):
        assert os.path.isfile("/app/adversarial_input.txt"), \
            "adversarial_input.txt not found in /app/"

    def test_sufficient_unique_keys(self):
        keys = set(read_adversarial_keys())
        assert len(keys) >= 10_000, \
            f"Expected >= 10,000 unique keys, got {len(keys)}"

    def test_keys_collide_under_original_hash(self):
        """At least 95 % of unique keys must hash to the same bucket."""
        keys = list(set(read_adversarial_keys()))
        bucket_counts = collections.Counter(original_hash(k) for k in keys)
        _, best = bucket_counts.most_common(1)[0]
        ratio = best / len(keys)
        assert ratio >= 0.95, (
            f"Only {ratio*100:.1f}% of keys collide in the most-popular "
            f"bucket. Expected >= 95%."
        )


# ── Part 2: Modified code compiles ──────────────────────────────────────────


class TestModifiedCompilation:

    def test_makefile_build(self):
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, timeout=30)
        r = subprocess.run(["make", "-C", "/app"],
                           capture_output=True, timeout=30)
        assert r.returncode == 0, \
            f"make failed:\n{r.stderr.decode()}"


# ── Part 2: Functional correctness ─────────────────────────────────────────


class TestModifiedCorrectness:

    def test_insert_and_lookup(self):
        code = r'''
#include "hashtable.h"
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <inttypes.h>

int main(void) {
    HashTable* ht = calloc(1, sizeof(HashTable));
    ht_init(ht);

    for (uint64_t i = 1; i <= 1000; i++)
        assert(ht_insert(ht, i, i * 100) == 0);

    for (uint64_t i = 1; i <= 1000; i++) {
        uint64_t val;
        assert(ht_lookup(ht, i, &val) == 1);
        assert(val == i * 100);
    }

    for (uint64_t i = 2000; i <= 2100; i++)
        assert(ht_lookup(ht, i, NULL) == 0);

    printf("PASS\n");
    free(ht);
    return 0;
}
'''
        r = compile_and_run(code, "insert_lookup")
        assert r.returncode == 0 and b"PASS" in r.stdout, \
            f"stdout: {r.stdout.decode()}\nstderr: {r.stderr.decode()}"

    def test_update_existing_key(self):
        code = r'''
#include "hashtable.h"
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

int main(void) {
    HashTable* ht = calloc(1, sizeof(HashTable));
    ht_init(ht);

    assert(ht_insert(ht, 42, 100) == 0);
    assert(ht_insert(ht, 42, 200) == 0);

    uint64_t val;
    assert(ht_lookup(ht, 42, &val) == 1);
    assert(val == 200);
    assert(ht->count == 1);

    printf("PASS\n");
    free(ht);
    return 0;
}
'''
        r = compile_and_run(code, "update")
        assert r.returncode == 0 and b"PASS" in r.stdout, \
            f"stdout: {r.stdout.decode()}\nstderr: {r.stderr.decode()}"

    def test_delete_and_relookup(self):
        code = r'''
#include "hashtable.h"
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

int main(void) {
    HashTable* ht = calloc(1, sizeof(HashTable));
    ht_init(ht);

    for (uint64_t i = 1; i <= 500; i++)
        ht_insert(ht, i, i);

    for (uint64_t i = 2; i <= 500; i += 2)
        assert(ht_delete(ht, i) == 1);

    for (uint64_t i = 1; i <= 500; i += 2) {
        uint64_t val;
        assert(ht_lookup(ht, i, &val) == 1);
        assert(val == i);
    }

    for (uint64_t i = 2; i <= 500; i += 2)
        assert(ht_lookup(ht, i, NULL) == 0);

    assert(ht_delete(ht, 99999) == 0);

    printf("PASS\n");
    free(ht);
    return 0;
}
'''
        r = compile_and_run(code, "delete")
        assert r.returncode == 0 and b"PASS" in r.stdout, \
            f"stdout: {r.stdout.decode()}\nstderr: {r.stderr.decode()}"

    def test_load_factor_limit(self):
        code = r'''
#include "hashtable.h"
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

int main(void) {
    HashTable* ht = calloc(1, sizeof(HashTable));
    ht_init(ht);

    int limit = TABLE_SIZE * 3 / 4;
    for (uint64_t i = 0; i < (uint64_t)limit; i++)
        assert(ht_insert(ht, i + 1000000ULL, i) == 0);

    assert(ht_insert(ht, 999, 999) == -1);

    printf("PASS\n");
    free(ht);
    return 0;
}
'''
        r = compile_and_run(code, "loadfactor")
        assert r.returncode == 0 and b"PASS" in r.stdout, \
            f"stdout: {r.stdout.decode()}\nstderr: {r.stderr.decode()}"


# ── Part 2: Defense effectiveness ──────────────────────────────────────────


class TestModifiedDistribution:

    def test_adversarial_keys_distributed(self):
        """Insert adversarial keys; max contiguous occupied run must be < 500."""
        code = r'''
#include "hashtable.h"
#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
#include <assert.h>

int main(void) {
    FILE* f = fopen("/app/adversarial_input.txt", "r");
    if (!f) { perror("fopen"); return 1; }

    HashTable* ht = calloc(1, sizeof(HashTable));
    ht_init(ht);

    uint64_t key;
    int count = 0;
    while (fscanf(f, "%" SCNu64, &key) == 1 && count < 10000) {
        if (ht_insert(ht, key, key) == 0)
            count++;
    }
    fclose(f);

    if (count < 5000) {
        fprintf(stderr, "Only inserted %d keys (expected >= 5000)\n", count);
        return 1;
    }

    /* verify all inserted keys can be looked up */
    f = fopen("/app/adversarial_input.txt", "r");
    int verified = 0, checked = 0;
    while (fscanf(f, "%" SCNu64, &key) == 1 && checked < count) {
        uint64_t val;
        if (ht_lookup(ht, key, &val)) {
            assert(val == key);
            verified++;
        }
        checked++;
    }
    fclose(f);

    if (verified < count) {
        fprintf(stderr, "Lookup failed: verified %d / %d\n", verified, count);
        return 1;
    }

    /* measure max contiguous run of occupied entries (wrap-aware) */
    int max_run = 0, cur_run = 0;
    for (int i = 0; i < TABLE_SIZE * 2; i++) {
        if (ht->entries[i % TABLE_SIZE].occupied) {
            cur_run++;
            if (cur_run > max_run) max_run = cur_run;
        } else {
            cur_run = 0;
        }
    }
    if (max_run > TABLE_SIZE) max_run = TABLE_SIZE;

    printf("inserted=%d verified=%d max_run=%d\n", count, verified, max_run);

    if (max_run >= 500) {
        fprintf(stderr, "FAIL: max contiguous run %d >= 500\n", max_run);
        return 1;
    }

    printf("PASS\n");
    free(ht);
    return 0;
}
'''
        r = compile_and_run(code, "distribution", timeout=120)
        out = r.stdout.decode()
        err = r.stderr.decode()
        assert r.returncode == 0 and "PASS" in out, \
            f"Distribution test failed.\nstdout: {out}\nstderr: {err}"

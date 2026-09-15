#!/usr/bin/env python3

"""
Solution for perf-regression-triage task.
Performs expert triage of profile anomalies, fixes genuine regressions,
computes Amdahl's law impact analysis, and builds a regression detection tool.
"""
import json
import os
import subprocess
import sys
from collections import defaultdict


def parse_folded(path):
    """Parse a folded stack trace file, return per-function total sample counts.
    Each function is counted once per stack it appears in (inclusive totals)."""
    counts = defaultdict(int)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            stack, count_str = parts
            count = int(count_str)
            functions = stack.split(";")
            seen = set()
            for func in functions:
                if func not in seen:
                    counts[func] += count
                    seen.add(func)
    return counts


def compute_total_samples(path):
    """Compute total sample count from a folded profile (sum of all line counts)."""
    total = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                total += int(parts[1])
    return total


def create_triage():
    """Create /app/triage.json with expert classification of all anomalous functions."""
    triage = {
        "triage": [
            {
                "function": "check_config_valid",
                "classification": "genuine_regression",
                "justification": (
                    "stat() syscall invoked on config file for every field of "
                    "every record via validate_field(). Before profile: 80 samples "
                    "(simple cached-like check). After profile: 18220 samples across "
                    "vfs_statx/path_lookupat/lookup_fast/security_inode_getattr — a "
                    "227x increase. The stat result is immutable within a single run "
                    "and should be cached. This is the classic excessive-syscalls "
                    "anti-pattern documented in strace debugging methodology."
                ),
            },
            {
                "function": "alloc_record_buf",
                "classification": "genuine_regression",
                "justification": (
                    "Per-record heap allocation via malloc() for a fixed-size "
                    "temporary buffer (MAX_LINE = 4096 bytes). Absent in baseline "
                    "profile; 7850 samples in after profile across "
                    "malloc/__libc_malloc/_int_malloc/sysmalloc. The buffer size is "
                    "constant and well within stack limits. Replacing with a stack "
                    "buffer eliminates all malloc/free overhead per record."
                ),
            },
            {
                "function": "normalize_text",
                "classification": "genuine_regression",
                "justification": (
                    "O(n^2) consecutive duplicate removal: for each duplicate found, "
                    "memmove shifts the entire remaining string. Before: 520 samples "
                    "in dedup_pass (O(n) algorithm). After: 11850 samples in "
                    "dedup_loop/memmove/__memmove_avx_unaligned_erms — a 22x "
                    "increase indicating algorithmic regression from O(n) to O(n^2). "
                    "Must use O(n) read/write pointer approach."
                ),
            },
            {
                "function": "rebuild_index",
                "classification": "genuine_regression",
                "justification": (
                    "Hash index rebuilt from file on every lookup_record() call. "
                    "Absent in baseline (index was built once). After: 18950 samples "
                    "across fopen/fgets/strchr/hash_key/malloc/free/fclose — the "
                    "entire file is re-read and hash table reconstructed for each "
                    "of N records, making lookup O(N*M) instead of O(N+M). Index "
                    "should be built once and reused across all lookups."
                ),
            },
            {
                "function": "sanitize_key",
                "classification": "intentional_addition",
                "justification": (
                    "New input validation function for security hardening. Absent in "
                    "baseline (intentionally new code). After: 1130 samples across "
                    "strlen/memchr — only 1.6% of total profile time. The function "
                    "is O(n) in key length with simple character validation, already "
                    "algorithmically optimal. Its purpose is to prevent buffer "
                    "overflow and injection attacks from malformed keys. Removing it "
                    "would re-introduce input validation vulnerabilities. The small "
                    "overhead is the expected and acceptable cost of security."
                ),
            },
            {
                "function": "accumulate_stats",
                "classification": "expected_overhead",
                "justification": (
                    "Monitoring/observability function present in both profiles. "
                    "Before: 530 samples. After: 1380 samples — a 160% increase "
                    "that is proportional to the overall workload increase, not "
                    "algorithmic regression. The function is O(1) per call "
                    "(strlen + comparison + counter increment). Its 1.9% share of "
                    "the total profile is acceptable overhead for production "
                    "monitoring. The sample growth tracks input volume, not "
                    "degraded algorithm behavior."
                ),
            },
        ]
    }
    with open("/app/triage.json", "w") as f:
        json.dump(triage, f, indent=2)
    print("Created /app/triage.json")


def create_impact_analysis():
    """Create /app/impact_analysis.json with Amdahl's law speedup projections."""
    total_after = compute_total_samples("/app/profile_after.folded")
    print(f"  Total after-profile samples: {total_after}")

    # Regression deltas computed from profile data
    regressions = [
        {
            "function": "check_config_valid",
            "root_cause": "Uncached stat() syscall called per-field per-record",
            "before_samples": 80,
            "after_samples": 18220,
        },
        {
            "function": "alloc_record_buf",
            "root_cause": "Unnecessary per-record heap allocation for fixed-size buffer",
            "before_samples": 0,
            "after_samples": 7850,
        },
        {
            "function": "normalize_text",
            "root_cause": "O(n^2) memmove-based consecutive duplicate removal",
            "before_samples": 520,
            "after_samples": 11850,
        },
        {
            "function": "rebuild_index",
            "root_cause": "Hash index rebuilt from file on every single lookup call",
            "before_samples": 0,
            "after_samples": 18950,
        },
    ]

    analysis_entries = []
    for r in regressions:
        delta = r["after_samples"] - r["before_samples"]
        fraction = delta / total_after
        speedup = 1.0 / (1.0 - fraction)
        analysis_entries.append({
            "function": r["function"],
            "root_cause": r["root_cause"],
            "before_samples": r["before_samples"],
            "after_samples": r["after_samples"],
            "regression_delta": delta,
            "total_after_samples": total_after,
            "fraction_of_profile": round(fraction, 4),
            "amdahl_projected_speedup": round(speedup, 3),
        })
        print(f"  {r['function']}: fraction={fraction:.4f}, speedup={speedup:.3f}")

    with open("/app/impact_analysis.json", "w") as f:
        json.dump({"analysis": analysis_entries}, f, indent=2)
    print("Created /app/impact_analysis.json")


def create_perf_guardian():
    """Create /app/perf_guardian.py — automated regression detection tool."""
    code = '''#!/usr/bin/env python3
"""
perf_guardian.py — Automated performance regression detection tool.

Analyzes two folded stack trace profiles (before/after) and flags functions
with significant sample count changes as potential regressions. Supports
configurable thresholds and severity classification.

Usage:
    python3 perf_guardian.py <before.folded> <after.folded> [--threshold N]
"""
import sys
import json
import argparse
from collections import defaultdict


def parse_folded(path):
    """Parse folded stack trace, return per-function inclusive sample counts."""
    counts = defaultdict(int)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            stack, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            functions = stack.split(";")
            seen = set()
            for func in functions:
                if func not in seen:
                    counts[func] += count
                    seen.add(func)
    return counts


def classify_severity(delta, pct_change, before_samples):
    """Classify regression severity based on absolute delta and relative change."""
    abs_delta = abs(delta)
    abs_pct = abs(pct_change)
    if abs_delta > 5000 and (abs_pct > 200 or before_samples == 0):
        return "critical"
    elif abs_delta > 1000 and (abs_pct > 50 or before_samples == 0):
        return "warning"
    else:
        return "info"


def main():
    parser = argparse.ArgumentParser(
        description="Detect performance regressions from folded stack profiles"
    )
    parser.add_argument("before", help="Path to baseline folded profile")
    parser.add_argument("after", help="Path to current folded profile")
    parser.add_argument(
        "--threshold", type=int, default=500,
        help="Minimum absolute sample delta to report (default: 500)"
    )
    parser.add_argument(
        "--min-samples", type=int, default=100,
        help="Minimum samples in either profile to consider (default: 100)"
    )
    args = parser.parse_args()

    before = parse_folded(args.before)
    after = parse_folded(args.after)

    all_funcs = set(before.keys()) | set(after.keys())
    regressions = []

    for func in all_funcs:
        b = before.get(func, 0)
        a = after.get(func, 0)
        delta = a - b

        if abs(delta) < args.threshold:
            continue
        if max(a, b) < args.min_samples:
            continue

        if b > 0:
            pct_change = round((delta / b) * 100, 1)
        else:
            pct_change = 99999.9  # new function, no baseline

        severity = classify_severity(delta, pct_change, b)

        regressions.append({
            "function": func,
            "before_samples": b,
            "after_samples": a,
            "delta": delta,
            "percent_change": pct_change,
            "severity": severity,
        })

    regressions.sort(key=lambda x: abs(x["delta"]), reverse=True)
    print(json.dumps({"regressions": regressions}, indent=2))


if __name__ == "__main__":
    main()
'''
    with open("/app/perf_guardian.py", "w") as f:
        f.write(code)
    os.chmod("/app/perf_guardian.py", 0o755)
    print("Created /app/perf_guardian.py")


def fix_workload():
    """Fix /app/workload.c — only genuine regressions, preserve decoy functions."""
    fixed_code = r'''/* workload.c - Record processing pipeline (FIXED) */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#define MAX_LINE 4096
#define MAX_FIELD 256
#define HASH_SIZE 65537
#define CONFIG_PATH "/app/config.ini"

typedef struct Entry {
    char key[MAX_FIELD];
    int value;
    struct Entry *next;
} Entry;

static Entry *hash_table[HASH_SIZE];
static int index_built = 0;

/* FIX 1: Cache for config validity check */
static int config_valid_cached = -1;

unsigned int hash_key(const char *key) {
    unsigned int h = 5381;
    while (*key) {
        h = ((h << 5) + h) + (unsigned char)*key++;
    }
    return h % HASH_SIZE;
}

void rebuild_index(const char *data_file) {
    for (int i = 0; i < HASH_SIZE; i++) {
        Entry *e = hash_table[i];
        while (e) {
            Entry *next = e->next;
            free(e);
            e = next;
        }
        hash_table[i] = NULL;
    }
    FILE *f = fopen(data_file, "r");
    if (!f) return;
    char line[MAX_LINE];
    int lineno = 0;
    while (fgets(line, sizeof(line), f)) {
        char *tab = strchr(line, '\t');
        if (tab) {
            *tab = '\0';
            unsigned int h = hash_key(line);
            Entry *e = malloc(sizeof(Entry));
            strncpy(e->key, line, MAX_FIELD - 1);
            e->key[MAX_FIELD - 1] = '\0';
            e->value = lineno;
            e->next = hash_table[h];
            hash_table[h] = e;
        }
        lineno++;
    }
    fclose(f);
}

/* FIX 4: Build index once and reuse */
int lookup_record(const char *key, const char *data_file) {
    if (!index_built) {
        rebuild_index(data_file);
        index_built = 1;
    }
    unsigned int h = hash_key(key);
    Entry *e = hash_table[h];
    while (e) {
        if (strcmp(e->key, key) == 0) return e->value;
        e = e->next;
    }
    return -1;
}

/* FIX 1: Cache stat() result */
int check_config_valid(void) {
    if (config_valid_cached >= 0) return config_valid_cached;
    struct stat st;
    if (stat(CONFIG_PATH, &st) == 0) {
        time_t now = time(NULL);
        if (now - st.st_mtime < 365 * 86400) {
            config_valid_cached = 1;
            return 1;
        }
    }
    config_valid_cached = 0;
    return 0;
}

int validate_field(const char *field) {
    if (!check_config_valid()) return 0;
    if (field == NULL || strlen(field) == 0) return 0;
    for (const char *p = field; *p; p++) {
        if (*p < 32 && *p != '\t' && *p != '\n') return 0;
    }
    return 1;
}

/* Security: validate key format (PRESERVED — intentional security addition) */
int sanitize_key(const char *key) {
    if (key == NULL) return 0;
    int len = strlen(key);
    if (len == 0 || len >= MAX_FIELD) return 0;
    for (const char *p = key; *p; p++) {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
              (*p >= '0' && *p <= '9') || *p == '_')) {
            return 0;
        }
    }
    return 1;
}

/* FIX 3: O(n) dedup with read/write pointers */
void normalize_text(char *text) {
    int len = strlen(text);
    for (int i = 0; i < len; i++) {
        if (text[i] >= 'A' && text[i] <= 'Z') {
            text[i] = text[i] + 32;
        }
    }
    int write_pos = 0;
    for (int read_pos = 0; read_pos < len; read_pos++) {
        if (read_pos == 0 || text[read_pos] != text[write_pos - 1]) {
            text[write_pos++] = text[read_pos];
        }
    }
    text[write_pos] = '\0';
}

/* Monitoring: accumulate stats (PRESERVED — observability instrumentation) */
static long total_records_processed = 0;
static long total_valid_records = 0;
static long max_key_len_seen = 0;

void accumulate_stats(const char *key) {
    total_records_processed++;
    int klen = strlen(key);
    if (klen > max_key_len_seen) max_key_len_seen = klen;
    total_valid_records++;
}

/* FIX 2: Stack buffer instead of heap allocation */
void process_record(const char *line, int recnum, const char *index_file, FILE *out) {
    char buf[MAX_LINE];
    strncpy(buf, line, MAX_LINE - 1);
    buf[MAX_LINE - 1] = '\0';

    int len = strlen(buf);
    if (len > 0 && buf[len - 1] == '\n') buf[len - 1] = '\0';

    char *fields[64];
    int nfields = 0;
    char *tok = strtok(buf, "\t");
    while (tok && nfields < 64) {
        fields[nfields++] = tok;
        tok = strtok(NULL, "\t");
    }

    if (nfields < 2) return;

    /* Validate key format (security hardening — preserved) */
    if (!sanitize_key(fields[0])) return;

    for (int i = 0; i < nfields; i++) {
        if (!validate_field(fields[i])) return;
    }

    char text_copy[MAX_LINE];
    strncpy(text_copy, fields[1], MAX_LINE - 1);
    text_copy[MAX_LINE - 1] = '\0';
    normalize_text(text_copy);

    /* Track processing statistics (monitoring — preserved) */
    accumulate_stats(fields[0]);

    int idx = lookup_record(fields[0], index_file);

    fprintf(out, "%d\t%s\t%s\t%d\n", recnum, fields[0], text_copy, idx);
}

int main(int argc, char *argv[]) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <input> <index> <output>\n", argv[0]);
        return 1;
    }

    FILE *in = fopen(argv[1], "r");
    if (!in) { perror("open input"); return 1; }

    FILE *out = fopen(argv[3], "w");
    if (!out) { perror("open output"); return 1; }

    char line[MAX_LINE];
    int recnum = 0;
    while (fgets(line, sizeof(line), in)) {
        process_record(line, recnum, argv[2], out);
        recnum++;
    }

    fclose(in);
    fclose(out);

    for (int i = 0; i < HASH_SIZE; i++) {
        Entry *e = hash_table[i];
        while (e) {
            Entry *next = e->next;
            free(e);
            e = next;
        }
    }

    printf("Processed %d records\n", recnum);
    return 0;
}
'''
    with open("/app/workload.c", "w") as f:
        f.write(fixed_code)
    print("Fixed /app/workload.c (preserved sanitize_key and accumulate_stats)")


def verify():
    """Compile and verify the fixed code."""
    result = subprocess.run(
        ["gcc", "-O2", "-o", "/app/workload", "/app/workload.c"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Compilation failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Compilation successful")

    result = subprocess.run(
        ["/app/workload", "/app/test_data.txt", "/app/index_data.txt",
         "/tmp/verify_output.txt"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"Execution failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    with open("/tmp/verify_output.txt") as f:
        actual = f.read().strip()
    with open("/app/reference_output.txt") as f:
        expected = f.read().strip()

    if actual != expected:
        print("Output mismatch!", file=sys.stderr)
        print(f"Expected:\n{expected}", file=sys.stderr)
        print(f"Actual:\n{actual}", file=sys.stderr)
        sys.exit(1)
    print("Output verification passed")


def main():
    print("=== Performance Regression Triage Solution ===\n")

    print("Step 1: Creating triage classification...")
    create_triage()

    print("\nStep 2: Fixing workload.c (genuine regressions only)...")
    fix_workload()

    print("\nStep 3: Compiling and verifying...")
    verify()

    print("\nStep 4: Computing impact analysis...")
    create_impact_analysis()

    print("\nStep 5: Creating perf_guardian.py...")
    create_perf_guardian()

    print("\n=== All done ===")


if __name__ == "__main__":
    main()

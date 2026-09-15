#!/usr/bin/env python3
"""
Correct FIMI-compliant Frequent Itemset Mining Tool.
Implements Eclat algorithm with all, closed, and maximal modes.
Outputs FIMI'04 format: total count first, then per-length counts.
Handles both standard FIMI format and non-standard raw formats.
"""


import sys
import os
import re

sys.setrecursionlimit(50000)


def parse_standard_fimi(filepath):
    """Parse a standard FIMI-format dataset."""
    transactions = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                transactions.append(frozenset(int(x) for x in line.split()))
    return transactions


def parse_raw_dataset(filepath):
    """Parse a non-standard dataset, auto-detecting format.

    Handles:
    - Comment lines (starting with #)
    - Pipe-separated fields (txn_id|items)
    - Comma-separated items
    - Duplicate items within transactions
    - Unsorted items
    """
    transactions = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Check for pipe separator (txn_id|items)
            if '|' in line:
                parts = line.split('|', 1)
                if len(parts) == 2:
                    line = parts[1]

            # Try comma-separated first, then space-separated
            if ',' in line:
                tokens = line.split(',')
            else:
                tokens = line.split()

            items = set()
            for token in tokens:
                token = token.strip()
                try:
                    items.add(int(token))
                except ValueError:
                    continue

            if items:
                transactions.append(frozenset(items))

    return transactions


def parse_dataset(filepath):
    """Parse a dataset, detecting format automatically."""
    # Check if it looks like a non-standard format
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # If line starts with # or contains | or , -> non-standard
            if line.startswith('#') or '|' in line or ',' in line:
                return parse_raw_dataset(filepath)
            # Try standard parse
            break

    return parse_standard_fimi(filepath)


def build_vertical(transactions):
    """Build vertical (item -> tid-set) representation."""
    vertical = {}
    for tid, txn in enumerate(transactions):
        for item in txn:
            if item not in vertical:
                vertical[item] = set()
            vertical[item].add(tid)
    return vertical


def mine_all(vertical, min_support, n_txn):
    """Mine all frequent itemsets using Eclat."""
    results = []
    if n_txn >= min_support:
        results.append((frozenset(), n_txn))

    freq_items = [
        (item, frozenset(tids))
        for item, tids in sorted(vertical.items())
        if len(tids) >= min_support
    ]

    def _eclat(prefix, items_tids):
        for i, (item, tids) in enumerate(items_tids):
            new_prefix = prefix | frozenset([item])
            results.append((new_prefix, len(tids)))
            new_items = []
            for j in range(i + 1, len(items_tids)):
                item2, tids2 = items_tids[j]
                new_tids = tids & tids2
                if len(new_tids) >= min_support:
                    new_items.append((item2, new_tids))
            if new_items:
                _eclat(new_prefix, new_items)

    _eclat(frozenset(), freq_items)
    return results


def mine_closed(vertical, min_support, n_txn):
    """Mine closed frequent itemsets."""
    freq_items = [
        (item, frozenset(tids))
        for item, tids in sorted(vertical.items())
        if len(tids) >= min_support
    ]
    freq_item_tidsets = {item: tids for item, tids in freq_items}

    results = []

    # Empty set closure check: closed iff no item appears in ALL transactions
    if n_txn >= min_support:
        empty_is_closed = all(len(t) < n_txn for t in freq_item_tidsets.values())
        if empty_is_closed:
            results.append((frozenset(), n_txn))

    def _eclat_closed(prefix, items_tids):
        for i, (item, tids) in enumerate(items_tids):
            new_prefix = prefix | frozenset([item])
            support = len(tids)

            # Closure check: X is closed iff no frequent item outside X
            # has tidset containing all of X's transactions
            is_closed = True
            for fi, fi_tids in freq_item_tidsets.items():
                if fi not in new_prefix and tids <= fi_tids:
                    is_closed = False
                    break

            if is_closed:
                results.append((new_prefix, support))

            new_items = []
            for j in range(i + 1, len(items_tids)):
                item2, tids2 = items_tids[j]
                new_tids = tids & tids2
                if len(new_tids) >= min_support:
                    new_items.append((item2, new_tids))
            if new_items:
                _eclat_closed(new_prefix, new_items)

    _eclat_closed(frozenset(), freq_items)
    return results


def mine_maximal(vertical, min_support, n_txn):
    """Mine maximal frequent itemsets."""
    all_results = mine_all(vertical, min_support, n_txn)
    all_sets = {items for items, _ in all_results}
    freq_items_set = frozenset(
        item for item, tids in vertical.items() if len(tids) >= min_support
    )

    maximal = []
    for itemset, support in all_results:
        if len(itemset) == 0:
            if not freq_items_set:
                maximal.append((itemset, support))
            continue
        is_maximal = True
        # Check ALL frequent items not in itemset (not just higher-ID ones)
        for item in freq_items_set:
            if item not in itemset and (itemset | frozenset([item])) in all_sets:
                is_maximal = False
                break
        if is_maximal:
            maximal.append((itemset, support))

    return maximal


def write_output(itemsets, filepath):
    """Write itemsets to file in FIMI format, including empty set."""
    with open(filepath, "w") as f:
        for itemset, support in itemsets:
            if len(itemset) == 0:
                f.write(f"({support})\n")
            else:
                items_str = " ".join(str(x) for x in sorted(itemset))
                f.write(f"{items_str} ({support})\n")


def print_fimi04_counts(itemsets):
    """Print FIMI'04 format: total count first, then per-length counts."""
    total = len(itemsets)
    print(total)

    if not itemsets:
        return

    max_len = max(len(s) for s, _ in itemsets)
    counts = [0] * (max_len + 1)
    for itemset, _ in itemsets:
        counts[len(itemset)] += 1
    for c in counts:
        print(c)


def main():
    if len(sys.argv) < 4:
        print(
            "Usage: fim <mode> <dataset> <min_support> [output_file]",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = sys.argv[1]
    dataset_path = sys.argv[2]
    min_support = int(sys.argv[3])
    output_file = sys.argv[4] if len(sys.argv) > 4 else None

    if mode not in ("all", "closed", "maximal"):
        print(f"Invalid mode: {mode}", file=sys.stderr)
        sys.exit(1)

    transactions = parse_dataset(dataset_path)
    n_txn = len(transactions)
    vertical = build_vertical(transactions)

    if mode == "all":
        results = mine_all(vertical, min_support, n_txn)
    elif mode == "closed":
        results = mine_closed(vertical, min_support, n_txn)
    elif mode == "maximal":
        results = mine_maximal(vertical, min_support, n_txn)

    print_fimi04_counts(results)

    if output_file:
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        write_output(results, output_file)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Complete the verification proofs in verified_algorithms.rs by adding
loop invariants, proof bodies, decreases clauses, ensures clauses,
broadcast use declarations, and proof blocks throughout the file.

"""

import sys

SOURCE = "/app/verified_algorithms.rs"


def apply_fixes():
    with open(SOURCE, "r") as f:
        content = f.read()

    original = content
    fixes_applied = 0

    # --- Fix 1: Add loop invariant to extend_from_idx ---
    # The for loop needs an invariant relating r@ to the subrange processed so far.
    old = (
        "    for i in start..v.len()\n"
        "    {\n"
        "        r.push(v[i]);\n"
        "    }"
    )
    new = (
        "    for i in start..v.len()\n"
        "        invariant\n"
        "            r@ =~= old(r)@ + v@.subrange(start as int, i as int),\n"
        "    {\n"
        "        r.push(v[i]);\n"
        "    }"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    # --- Fix 2: Complete lemma_to_multiset_distributes_over_add ---
    # Need: decreases clause for termination + full inductive proof body
    old = (
        "        #[trigger] (s1 + s2).to_multiset() =~= s1.to_multiset().add(s2.to_multiset()),\n"
        "{\n"
        "    assume(false);\n"
        "}"
    )
    new = (
        "        #[trigger] (s1 + s2).to_multiset() =~= s1.to_multiset().add(s2.to_multiset()),\n"
        "    decreases s2.len(),\n"
        "{\n"
        "    s2.to_multiset_ensures();\n"
        "    if s2.len() == 0 {\n"
        "        assert((s1 + s2).to_multiset() =~= s1.to_multiset());\n"
        "        assert(s2.to_multiset() =~= Multiset::<u64>::empty());\n"
        "    } else {\n"
        "        lemma_to_multiset_distributes_over_add(s1, s2.drop_last());\n"
        "        vstd::seq::Seq::drop_last_distributes_over_add(s1, s2);\n"
        "        assert(s2.drop_last() =~= s2.remove(s2.len() - 1));\n"
        "        assert(s1 + s2 =~= (s1 + s2).drop_last().push(s2[(s2.len() - 1) as int]));\n"
        "        assert((s1 + s2).to_multiset() =~= ((s1 + s2).drop_last().push(\n"
        "            s2[(s2.len() - 1) as int],\n"
        "        )).to_multiset());\n"
        "        (s1 + s2).drop_last().to_multiset_ensures();\n"
        "    }\n"
        "}"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    # --- Fix 3: Add ensures clause to lemma_subrange_push ---
    # The lemma needs an ensures clause stating what it proves, and assume(false) removed.
    old = (
        "proof fn lemma_subrange_push(s1: Seq<u64>, start: int, end: int)\n"
        "    requires\n"
        "        0 <= start <= end < s1.len(),\n"
        "{\n"
        "    assume(false);\n"
        "}"
    )
    new = (
        "proof fn lemma_subrange_push(s1: Seq<u64>, start: int, end: int)\n"
        "    requires\n"
        "        0 <= start <= end < s1.len(),\n"
        "    ensures\n"
        "        s1.subrange(start, end).push(s1[end]) =~= s1.subrange(start, end + 1),\n"
        "{\n"
        "}"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    # --- Fix 4a: Add broadcast use to merge function ---
    # Multiset distribution facts must be made available in the proof context.
    old = (
        "    let mut r: Vec<u64> = Vec::new();\n"
        "    let mut i1: usize = 0;\n"
        "    let mut i2: usize = 0;"
    )
    new = (
        "    broadcast use lemma_to_multiset_distributes_over_add;\n"
        "\n"
        "    let mut r: Vec<u64> = Vec::new();\n"
        "    let mut i1: usize = 0;\n"
        "    let mut i2: usize = 0;"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    # --- Fix 4b: Add loop invariants and proof blocks to merge's while loop ---
    old = (
        "    while i1 < v1.len() && i2 < v2.len()\n"
        "        decreases v1.len() + v2.len() - i1 - i2,\n"
        "    {\n"
        "        if v1[i1] < v2[i2] {\n"
        "            r.push(v1[i1]);\n"
        "            i1 += 1;\n"
        "        } else {\n"
        "            r.push(v2[i2]);\n"
        "            i2 += 1;\n"
        "        }\n"
        "    }"
    )
    new = (
        "    while i1 < v1.len() && i2 < v2.len()\n"
        "        invariant\n"
        "            0 <= i1 <= v1.len(),\n"
        "            0 <= i2 <= v2.len(),\n"
        "            is_sorted(v1),\n"
        "            is_sorted(v2),\n"
        "            forall|i: int| i1 < v1.len() ==> 0 <= i < r.len() ==> r[i] <= v1[i1 as int],\n"
        "            forall|i: int| i2 < v2.len() ==> 0 <= i < r.len() ==> r[i] <= v2[i2 as int],\n"
        "            r@.to_multiset() =~= (v1@.subrange(0 as int, i1 as int) + v2@.subrange(\n"
        "                0 as int,\n"
        "                i2 as int,\n"
        "            )).to_multiset(),\n"
        "            is_sorted(&r),\n"
        "        decreases v1.len() + v2.len() - i1 - i2,\n"
        "    {\n"
        "        proof {\n"
        "            r@.to_multiset_ensures();\n"
        "        }\n"
        "        if v1[i1] < v2[i2] {\n"
        "            r.push(v1[i1]);\n"
        "            proof {\n"
        "                lemma_to_multiset_distributes_over_add(\n"
        "                    v1@.subrange(0 as int, i1 as int),\n"
        "                    v2@.subrange(0 as int, i2 as int),\n"
        "                );\n"
        "                v1@.subrange(0 as int, i1 as int).to_multiset_ensures();\n"
        "                lemma_subrange_push(v1@, 0 as int, i1 as int);\n"
        "                lemma_to_multiset_distributes_over_add(\n"
        "                    v1@.subrange(0 as int, (i1 + 1) as int),\n"
        "                    v2@.subrange(0 as int, i2 as int),\n"
        "                );\n"
        "            }\n"
        "            i1 += 1;\n"
        "        } else {\n"
        "            r.push(v2[i2]);\n"
        "            proof {\n"
        "                lemma_to_multiset_distributes_over_add(\n"
        "                    v1@.subrange(0 as int, i1 as int),\n"
        "                    v2@.subrange(0 as int, i2 as int),\n"
        "                );\n"
        "                v2@.subrange(0 as int, i2 as int).to_multiset_ensures();\n"
        "                lemma_subrange_push(v2@, 0 as int, i2 as int);\n"
        "                lemma_to_multiset_distributes_over_add(\n"
        "                    v1@.subrange(0 as int, i1 as int),\n"
        "                    v2@.subrange(0 as int, (i2 + 1) as int),\n"
        "                );\n"
        "            }\n"
        "            i2 += 1;\n"
        "        }\n"
        "\n"
        "    }"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    # --- Fix 4c: Add proof blocks after merge's while loop ---
    old = (
        "    if i1 < v1.len() {\n"
        "        extend_from_idx(&mut r, v1, i1);\n"
        "    } else if i2 < v2.len() {\n"
        "        extend_from_idx(&mut r, v2, i2);\n"
        "    }\n"
        "    r\n"
        "}"
    )
    new = (
        "    if i1 < v1.len() {\n"
        "        extend_from_idx(&mut r, v1, i1);\n"
        "        proof {\n"
        "            lemma_subrange_add(v1@, 0 as int, i1 as int, v1.len() as int);\n"
        "            assert(r@.to_multiset() =~= (v1@ + v2@).to_multiset());\n"
        "        }\n"
        "    } else if i2 < v2.len() {\n"
        "        extend_from_idx(&mut r, v2, i2);\n"
        "        proof {\n"
        "            lemma_subrange_add(v2@, 0 as int, i2 as int, v2.len() as int);\n"
        "            assert(r@.to_multiset() =~= (v1@ + v2@).to_multiset());\n"
        "        }\n"
        "    }\n"
        "    r\n"
        "}"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    # --- Fix 5: Add proof blocks to merge_sort ---
    old = (
        "        assert(v1@ + v2@ == v@);\n"
        "        let r1 = merge_sort(&mut v1);\n"
        "        let r2 = merge_sort(&mut v2);\n"
        "        let r = merge(&r1, &r2);"
    )
    new = (
        "        assert(v1@ + v2@ == v@);\n"
        "        proof {\n"
        "            lemma_to_multiset_distributes_over_add(v1@, v2@);\n"
        "        }\n"
        "        let r1 = merge_sort(&mut v1);\n"
        "        let r2 = merge_sort(&mut v2);\n"
        "        proof {\n"
        "            lemma_to_multiset_distributes_over_add(r1@, r2@);\n"
        "        }\n"
        "        let r = merge(&r1, &r2);"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    # --- Fix 6: Add loop invariants to binary_search ---
    old = (
        "    while lo != hi\n"
        "        decreases hi - lo,\n"
        "    {"
    )
    new = (
        "    while lo != hi\n"
        "        invariant\n"
        "            hi < v.len(),\n"
        "            is_sorted(v),\n"
        "            exists|i: int| lo <= i <= hi && k == v[i],\n"
        "        decreases hi - lo,\n"
        "    {"
    )
    if old in content:
        content = content.replace(old, new)
        fixes_applied += 1

    if content == original:
        print("WARNING: No changes were applied. The file may have already been fixed.")
        return False

    with open(SOURCE, "w") as f:
        f.write(content)

    print(f"Applied {fixes_applied} fix(es) successfully.")
    return True


if __name__ == "__main__":
    success = apply_fixes()
    if success:
        print("All verification fixes applied.")
    else:
        print("Fix application may have failed.")
        sys.exit(1)

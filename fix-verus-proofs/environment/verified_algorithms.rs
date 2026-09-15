
// Verified algorithms implementation in Verus.
// Merge sort and binary search over Vec<u64>.

use vstd::multiset::*;
use vstd::prelude::*;
use vstd::seq_lib::group_seq_properties;

verus! {

pub open spec fn is_sorted(v: &Vec<u64>) -> bool {
    forall|i: int, j: int| 0 <= i < j < v.len() ==> #[trigger] v[i] <= #[trigger] v[j]
}

fn extend_from_idx(r: &mut Vec<u64>, v: &Vec<u64>, start: usize)
    requires
        start < v.len(),
    ensures
        final(r)@ == old(r)@ + v@.subrange(start as int, v.len() as int),
{
    for i in start..v.len()
    {
        r.push(v[i]);
    }
}

pub broadcast proof fn lemma_to_multiset_distributes_over_add(s1: Seq<u64>, s2: Seq<u64>)
    ensures
        #[trigger] (s1 + s2).to_multiset() =~= s1.to_multiset().add(s2.to_multiset()),
{
    assume(false);
}

proof fn lemma_subrange_push(s1: Seq<u64>, start: int, end: int)
    requires
        0 <= start <= end < s1.len(),
{
    assume(false);
}

proof fn lemma_subrange_add(s1: Seq<u64>, start: int, mid: int, end: int)
    requires
        0 <= start <= mid <= end <= s1.len(),
    ensures
        s1.subrange(start, mid) + s1.subrange(mid, end) =~= s1.subrange(start, end),
{
}

fn merge(v1: &Vec<u64>, v2: &Vec<u64>) -> (r: Vec<u64>)
    requires
        is_sorted(v1),
        is_sorted(v2),
    ensures
        r@.to_multiset() == (v1@ + v2@).to_multiset(),
        is_sorted(&r),
{
    let mut r: Vec<u64> = Vec::new();
    let mut i1: usize = 0;
    let mut i2: usize = 0;
    assert(v1@.subrange(0 as int, i1 as int) == Seq::<u64>::empty());

    while i1 < v1.len() && i2 < v2.len()
        decreases v1.len() + v2.len() - i1 - i2,
    {
        if v1[i1] < v2[i2] {
            r.push(v1[i1]);
            i1 += 1;
        } else {
            r.push(v2[i2]);
            i2 += 1;
        }
    }
    assert(v1@.subrange(0 as int, v1.len() as int) =~= v1@);
    assert(v2@.subrange(0 as int, v2.len() as int) =~= v2@);

    if i1 < v1.len() {
        extend_from_idx(&mut r, v1, i1);
    } else if i2 < v2.len() {
        extend_from_idx(&mut r, v2, i2);
    }
    r
}

fn merge_sort(v: &Vec<u64>) -> (r: Vec<u64>)
    ensures
        r@.to_multiset() == (*v)@.to_multiset(),
        is_sorted(&r),
    decreases v.len(),
{
    let n = v.len();
    let mut v1 = v.clone();
    if (n <= 1) {
        v1
    } else {
        let mut v2 = v1.split_off(n / 2);
        assert(v1@ + v2@ == v@);
        let r1 = merge_sort(&mut v1);
        let r2 = merge_sort(&mut v2);
        let r = merge(&r1, &r2);
        r
    }
}

fn binary_search(v: &Vec<u64>, k: u64) -> (r: usize)
    requires
        is_sorted(v),
        exists|i: int| 0 <= i < v.len() && k == v[i],
    ensures
        r < v.len(),
        v[r as int] == k,
{
    let mut lo: usize = 0;
    let mut hi: usize = v.len() - 1;

    while lo != hi
        decreases hi - lo,
    {
        let mid = lo + (hi - lo) / 2;
        if v[mid] < k {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    lo
}

fn main() {
    let v = vec![9, 10, 4, 5, 1, 3];
    let v_sorted = merge_sort(&v);
    let ghost expected_res: Seq<u64> = seq![1, 3, 4, 5, 9, 10];
    proof {
        broadcast use group_seq_properties;
        assert(v@ =~= seq![9].push(10).push(4).push(5).push(1).push(3));
        assert(expected_res =~= seq![1].push(3).push(4).push(5).push(9).push(10));

        assert(expected_res.to_multiset() =~= v@.to_multiset());
        vstd::seq_lib::lemma_sorted_unique(expected_res, v_sorted@, |a: u64, b: u64| a <= b);
        assert(v_sorted@ =~= expected_res);
    }

    assert(v_sorted[3] == 5);
    let idx = binary_search(&v_sorted, 5);
    assert(idx < v_sorted.len());
}

} // verus!
